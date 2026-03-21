"""GARCH-LSTM Hybrid Model for Volatility Prediction.

Design (from 2024-2025 literature survey):
1. Fit GJR-GARCH on training window -> get conditional variance sigma2_t
2. Compute standardized residuals: z_t = r_t / sigma_t
3. If GARCH is perfect, z_t ~ iid N(0,1). Any structure in z_t is what DL can capture.
4. Train LSTM on z2 sequences to predict next-day adjustment factor
5. Final forecast: sigma2_hybrid = sigma2_garch * LSTM_factor

Key insight: GARCH already captures volatility clustering (the dominant pattern).
LSTM only needs to learn the residual structure, which requires much less data.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from arch import arch_model
from volpred.data.manager import DataManager
from volpred.memory.system import MemorySystem


class ResidualLSTM(nn.Module):
    """Small LSTM for learning residual structure in GARCH standardized residuals."""

    def __init__(self, input_size=1, hidden_size=32, num_layers=2, dropout=0.2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                           batch_first=True, dropout=dropout)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Softplus(),  # Output > 0 (adjustment factor)
        )

    def forward(self, x):
        # x: (batch, seq_len, 1)
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # Take last timestep
        return self.fc(last_hidden)


def run_hybrid_experiment(asset='SPY', oos_start='2025-01-01', oos_end='2025-12-31',
                          garch_window=504, lookback=22, hidden_size=32,
                          num_layers=2, epochs=50, lr=0.001):
    """Run GARCH-LSTM hybrid experiment."""
    print(f"\n{'='*60}")
    print(f"GARCH-LSTM Hybrid: {asset}, OOS={oos_start}~{oos_end}")
    print(f"GARCH window={garch_window}, LSTM lookback={lookback}")
    print(f"LSTM: hidden={hidden_size}, layers={num_layers}, epochs={epochs}")
    print(f"{'='*60}")

    # 1. Get data
    dm = DataManager()
    buffer_days = int(garch_window * 1.5) + 252
    buffer_start = (pd.Timestamp(oos_start) - pd.DateOffset(days=buffer_days)).strftime('%Y-%m-%d')
    data = dm.get_model_data(asset, buffer_start, oos_end)
    returns = data['returns']

    oos_mask = (data.index >= pd.Timestamp(oos_start)) & (data.index <= pd.Timestamp(oos_end))
    oos_dates = data.index[oos_mask]

    print(f"Data: {len(data)} rows, {data.index[0].date()} ~ {data.index[-1].date()}")
    print(f"OOS dates: {len(oos_dates)}")

    # 2. For each OOS date: fit GARCH, collect residuals
    garch_forecasts = []
    all_residuals = []

    for target_date in oos_dates:
        target_loc = data.index.get_loc(target_date)
        train_returns = returns.iloc[target_loc - garch_window:target_loc]

        am = arch_model(train_returns * 100, vol='GARCH', p=1, o=1, q=1,
                        dist='normal', mean='Zero')
        res = am.fit(disp='off')

        cond_var = res.conditional_volatility ** 2 / 10000
        forecast = res.forecast(horizon=1)
        var_forecast = forecast.variance.values[-1, 0] / 10000

        std_resid = (train_returns.values * 100) / res.conditional_volatility.values

        garch_forecasts.append({
            'date': target_date,
            'garch_var': var_forecast,
            'actual_r2': returns.iloc[target_loc] ** 2,
        })
        all_residuals.append(std_resid)

    # 3. Build LSTM training data from IS residuals
    n_train = int(len(all_residuals) * 0.7)

    X_train, y_train = [], []
    for resid_seq in all_residuals[:n_train]:
        z2 = resid_seq ** 2
        for t in range(lookback, len(z2)):
            X_train.append(z2[t-lookback:t])
            y_train.append(z2[t])

    X_train = torch.FloatTensor(np.array(X_train)).unsqueeze(-1)
    y_train = torch.FloatTensor(np.array(y_train)).unsqueeze(-1)

    print(f"LSTM training: {len(X_train)} sequences, lookback={lookback}")

    # 4. Train LSTM
    model = ResidualLSTM(input_size=1, hidden_size=hidden_size,
                         num_layers=num_layers, dropout=0.2)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    model.train()
    dataset = torch.utils.data.TensorDataset(X_train, y_train)
    loader = torch.utils.data.DataLoader(dataset, batch_size=64, shuffle=True)

    for epoch in range(epochs):
        total_loss = 0
        for batch_x, batch_y in loader:
            optimizer.zero_grad()
            pred = model(batch_x)
            loss = loss_fn(pred, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        if (epoch + 1) % 10 == 0:
            avg_loss = total_loss / len(loader)
            print(f"  Epoch {epoch+1}/{epochs}, Loss: {avg_loss:.6f}")

    # 5. Generate hybrid forecasts
    model.eval()
    hybrid_forecasts = []

    for i, fc in enumerate(garch_forecasts):
        resid_seq = all_residuals[i]
        z2 = resid_seq ** 2
        current_factor = 1.0

        if len(z2) >= lookback:
            with torch.no_grad():
                x = torch.FloatTensor(z2[-lookback:]).unsqueeze(0).unsqueeze(-1)
                current_factor = model(x).item()

            hybrid_var = fc['garch_var'] * current_factor
        else:
            hybrid_var = fc['garch_var']

        hybrid_forecasts.append({
            'date': fc['date'],
            'garch_var': fc['garch_var'],
            'hybrid_var': hybrid_var,
            'lstm_factor': current_factor,
            'actual_r2': fc['actual_r2'],
        })

    # 6. Compute QLIKE
    df = pd.DataFrame(hybrid_forecasts)

    garch_qlike = np.mean(np.log(df['garch_var']) + df['actual_r2'] / df['garch_var'])
    hybrid_qlike = np.mean(np.log(df['hybrid_var']) + df['actual_r2'] / df['hybrid_var'])

    print(f"\n{'='*40}")
    print(f"Results ({len(df)} forecasts):")
    print(f"  GARCH-only QLIKE: {garch_qlike:.6f}")
    print(f"  Hybrid QLIKE:     {hybrid_qlike:.6f}")
    improvement = (garch_qlike - hybrid_qlike) / abs(garch_qlike) * 100
    print(f"  Improvement:      {improvement:.3f}%")
    print(f"  Mean LSTM factor: {df['lstm_factor'].mean():.4f}")
    print(f"  Std LSTM factor:  {df['lstm_factor'].std():.4f}")
    print(f"{'='*40}")

    return df, garch_qlike, hybrid_qlike


if __name__ == '__main__':
    m = MemorySystem()

    df, garch_q, hybrid_q = run_hybrid_experiment(
        asset='SPY',
        oos_start='2025-01-01',
        oos_end='2025-12-31',
        garch_window=504,
        lookback=22,
        hidden_size=32,
        num_layers=2,
        epochs=50,
    )

    improvement = (garch_q - hybrid_q) / abs(garch_q) * 100
    m.add_knowledge(
        category='model_behavior',
        content=(f'GARCH-LSTM hybrid (SPY, OOS=2025, GJR w=504, LSTM lookback=22, '
                 f'hidden=32, layers=2, epochs=50): '
                 f'GARCH QLIKE={garch_q:.6f}, Hybrid QLIKE={hybrid_q:.6f}, '
                 f'Improvement={improvement:.3f}%, '
                 f'Mean LSTM factor={df["lstm_factor"].mean():.4f}'),
        evidence=['garch_lstm_hybrid_2025'],
        confidence=0.85
    )

    if improvement > 0:
        m.think(
            f'GARCH-LSTM hybrid improved by {improvement:.3f}%. '
            f'LSTM factor mean={df["lstm_factor"].mean():.4f}. '
            f'GARCH residuals have learnable structure.'
        )
    else:
        m.think(
            f'GARCH-LSTM hybrid did not improve ({improvement:.3f}%). '
            f'GARCH residuals may be close to iid. '
            f'LSTM factor mean={df["lstm_factor"].mean():.4f}.'
        )

    print("\nDone. Results recorded to knowledge base.")
