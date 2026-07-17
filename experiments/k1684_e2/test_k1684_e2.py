"""K1684 E2 regression test — 鎖住統計機制正確性與 lag-safety。

跑法（worktree 內用 --extra dev；memory reference_worktree_pytest_wrong_interpreter）：
    uv run --extra dev python -m pytest experiments/k1684_e2/test_k1684_e2.py -q
"""
import importlib.util
import os

import numpy as np
from scipy import stats

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("k1684_e2_mod", os.path.join(_HERE, "k1684_e2.py"))
k2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k2)

from volpred.stats.model_evaluation import qlike_pointwise


def test_qlike_direction():
    """QLIKE：接近真變異數的預測應有較低 QLIKE（canonical actual/predicted 方向）。"""
    rng = np.random.default_rng(0)
    h = 1e-4 * (1 + 0.3 * np.sin(np.arange(3000) / 40)) ** 2
    r = rng.normal(0, np.sqrt(h))
    actual = r ** 2 + 1e-10
    assert qlike_pointwise(actual, h).mean() < qlike_pointwise(actual, 3 * h).mean()


def test_fz0_minimized_at_true_scale():
    """FZ0 sign 正確：對 v,e 同時縮放 k，損失在真尺度 k=1 附近最小（防 sign 反轉 regression）。"""
    rng = np.random.default_rng(1)
    sig = 0.01 * (1 + 0.2 * np.sin(np.arange(6000) / 40))
    r = rng.normal(0, sig)
    alpha = 0.05
    zq = stats.norm.ppf(alpha)
    esm = k2.normal_es_mult(alpha)
    ks = np.linspace(0.5, 2.0, 16)
    fz = [np.nanmean(k2.fz0_loss(r, k * sig * zq, k * sig * esm, alpha)) for k in ks]
    assert abs(ks[int(np.argmin(fz))] - 1.0) < 0.15


def test_kupiec_zero_violation_not_autopass():
    """零違規在 5% 下必須拒絕（LR_uc 決定性），不可回 p=1（修 E1 記錄的父檔 bug）。"""
    viol0 = np.zeros(500, int)
    assert k2.kupiec_pof(viol0, 0.05)["p"] < 0.01


def test_christoffersen_isolated_violations_ok():
    """孤立違規（t11=0）不應被 independence 短路成 p=1；CC 對 4 個孤立違規應不顯著（不拒絕）。"""
    v = np.zeros(500, int)
    v[[10, 120, 300, 450]] = 1
    cc = k2.christoffersen_cc(v, 0.01)
    assert cc["p_cc"] > 0.05 and cc["p_ind"] > 0.05


def test_z1_rejects_fat_tail_not_normal():
    """Z1：Normal 資料 vs Normal ES 不拒絕；t3 厚尾資料 vs Normal ES 應拒絕（ES 低估）。"""
    rng = np.random.default_rng(2)
    sig = 0.01 * np.ones(6000)
    alpha = 0.05
    v = sig * stats.norm.ppf(alpha)
    e = sig * k2.normal_es_mult(alpha)
    r_norm = rng.normal(0, sig)
    r_t = stats.t.rvs(3, size=6000, random_state=3) * sig / np.sqrt(3)
    z_ok = k2.acerbi_szekely_z1(r_norm, v, e, alpha, sig, "normal", None, 7)
    z_bad = k2.acerbi_szekely_z1(r_t, v, e, alpha, sig, "normal", None, 7)
    assert not z_ok["reject_es_underestimate_5pct"]
    assert z_bad["z1"] > 0 and z_bad["reject_es_underestimate_5pct"]


def test_hln_factor_large_n():
    """Harvey(1997) 小樣本修正因子在 h=1、大 n 應 ~1。"""
    assert abs(k2.hln_factor(5000, 1) - 1.0) < 1e-3


def test_recalibrate_is_lag_safe():
    """recalibrate 只用 <= t-1 的已實現 → 污染未來 target 不改變早期校正值。"""
    rng = np.random.default_rng(4)
    n = 2000
    oos = 800
    fc = np.abs(rng.normal(1e-4, 3e-5, n))
    tgt = fc * 0.7 + np.abs(rng.normal(0, 1e-5, n))
    base = k2.recalibrate(fc, tgt, oos)
    tgt2 = tgt.copy()
    tgt2[1500:] *= 10.0  # 污染未來
    pert = k2.recalibrate(fc, tgt2, oos)
    m = np.isfinite(base[oos:1500]) & np.isfinite(pert[oos:1500])
    assert np.allclose(base[oos:1500][m], pert[oos:1500][m], rtol=0, atol=0)


def test_recalibrate_removes_level_bias():
    """recalibrate 後預測對 target 均值近似無偏（消除 level bias）。"""
    rng = np.random.default_rng(5)
    n = 3000
    oos = 800
    tgt = np.abs(rng.normal(1e-4, 3e-5, n))
    fc = tgt * 1.8  # 系統性高估
    rc = k2.recalibrate(fc, tgt, oos)
    ratio = np.nanmean(tgt[oos + 200:] / rc[oos + 200:])
    assert 0.9 < ratio < 1.1
