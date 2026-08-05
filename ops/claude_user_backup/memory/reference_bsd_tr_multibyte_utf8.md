---
name: reference-bsd-tr-multibyte-utf8
description: "macOS 內建 BSD tr 不支援多位元組 UTF-8 字元，`tr ' ' '█'` 會把字元拆散成無效 bytes 導致亂碼"
metadata: 
  node_type: memory
  type: reference
  originSessionId: dd2c8bcc-5dcd-4b94-aabb-1875018afb0a
  modified: 2026-08-05T05:22:39.093Z
---

macOS 內建的 `tr`（BSD 版，非 GNU coreutils）逐 byte 處理，不是 Unicode-character-aware。
任何 `tr <x> '<多位元組UTF-8字元>'` 這種寫法都會壞掉：三個 byte 的字元（例如 `█` U+2588
= `E2 96 88`）只會取到第一個 byte 當替換目標，重複輸出變成一串無效、缺後續 byte 的
UTF-8（例如 5 次替換變成 `E2 E2 E2 E2 E2`），終端機只能盡力猜著顯示 → 呈現一堆看起來
像亂碼/blob 的字元，**外觀上很容易被誤判成字型缺字 glyph**（2026-08-05 debug 花了一整個
session 換了 6+ 種 Nerd Font 才發現其實是這個，字型從頭到尾都沒有問題）。

**症狀識別**：進度條 / bar 類的視覺元素用「重複某個方塊字元」畫出來，且看起來是一致的
亂碼 blob（不是缺字的空心 tofu 方框），同時你剛好在讀的是一段自己寫的 bash script 用
`tr ' ' '<某個特殊字元>'` 產生重複字元 —— 先懷疑這個，不要先懷疑字型。

**修法**：不要用 `tr` 重複多位元組字元。改用不逐 byte 拆解的寫法：

```bash
repeat_char() {
    local char="$1" count="$2" out=""
    local i
    for ((i = 0; i < count; i++)); do out+="$char"; done
    printf '%s' "$out"
}
BAR="$(repeat_char '█' "$FILLED")$(repeat_char '░' "$EMPTY")"
```

**額外陷阱**：macOS 的 BSD `seq` 在 `seq 1 0`（first > last，遞減無效範圍）**不是回傳空字串**，
會印出 `1` 和 `0` 兩行（跟 GNU seq 行為不同）——所以 `printf 'x%.0s' $(seq 1 $N)` 這種常見寫法
在 `$N=0` 時會壞掉（多印兩次而不是零次）。上面的 for-loop 寫法天生不受這個影響，優先用它。

實際案例：`~/.claude/statusline-command.sh`（Claude Code 自訂 status line script，本機
`~/.claude/settings.json` 的 `statusLine.command` 指到它）進度條用 `tr ' ' '█'`，在
`LANG`/`LC_ALL` 皆未設的互動 shell 下每次都壞。已修正並驗證全 0-100% range。

相關：[[reference-shell-utf8-locale-required]]（同樣是 UTF-8 locale 缺失類症狀，但那條講
Python argv/heredoc，這條講 shell 內建工具 tr/seq 本身的 byte-level 限制，觸發條件不同）
