# visordemo — SensoPart VISOR 影像擷取(library + CLI + web UI)

visordemo 是一個純 Python(零相依)的 SensoPart VISOR 視覺感測器影像擷取工具,同一套程式提供三種用法:當 **library** 匯入(`with Camera(host) as cam: ...`)、當 **CLI** 操作(`visordemo snapshot -o shot.png`)、或啟動內建 **web UI** 即時預覽。介面刻意做成與 [webcamdemo](https://github.com/yazelin/webcamdemo) 相容,消費端(如品檢站)把 `camera_factory` 換掉即可從 USB webcam 切換到 VISOR。

## 原理

VISOR 感測器的 request/response 通道(預設 TCP port 2006)支援 ASCII telegram:

- `TRG` — 觸發一次取像,回 `TRGP`(Pass)/`TRGF`(Fail)
- `GIMx` — Get Image(x:0=最後一張、1=最後 NG、2=最後 OK),回 15 bytes header(良否、影像型別、rows、cols)+ rows×cols 的 raw 8-bit 影像資料

visordemo 把 `TRG` + `GIM` 包成一次 `capture()`,raw 灰階直接以 stdlib zlib 編成 PNG 落地(彩色機種的 Bayer 影像自動 demosaic 成半解析度 RGB)。依據官方 [VISOR Communications Manual 068-14859](https://www.sensopart.com/en/service/downloads/)(2024-04 版)。

除取像外,已實作的控制指令:

| 功能 | Telegram | Library | CLI |
|---|---|---|---|
| 觸發取像 | TRG + GIM | `capture()` / `read_png()` | `snapshot` |
| 對焦(讀/設/自動) | GFC / SFC / AFC | `get_focus()` / `set_focus(mm)` / `autofocus()` | `focus [mm] [--auto]` |
| 快門(讀/設/自動) | GSH / SST·SSP / ASH | `get_shutter()` / `set_shutter(ms)` / `auto_shutter()` | `shutter [ms] [--auto]` |
| 增益(讀/設) | GGA / SGA | `get_gain()` / `set_gain(x)` | `gain [x]` |
| Job 清單/切換 | GJL / CJB·CJP·CJN | `jobs()` / `set_job(n或名稱)` | `job [n或名稱]` |
| 機型識別 | GSI | `identity()` | `info` |
| 光學內參與 FOV | CGP 010 | `internal_params()` / `fov(mm)` | `info` |

set 類指令預設 temporary(斷電還原),`--permanent` / `permanent=True` 才寫入 job。`set_shutter`/`set_gain` 都會讀回驗證,設不上會丟 `VisorError` 而不是靜默失敗。

## 安裝

```bash
git clone https://github.com/yazelin/visordemo.git
cd visordemo
uv tool install --editable .   # 裝好後直接有 visordemo 指令

# 或免安裝(零相依):
python3 -m visordemo.cli snapshot --host 192.168.2.100
```

## 快速開始

```bash
visordemo snapshot --host 192.168.2.100 -o shot.png   # 觸發 + 取像存 PNG
visordemo snapshot --no-trigger --which 2              # 不觸發,取最後一張 OK 影像
visordemo trigger --host 192.168.2.100                 # 只觸發,exit code 反映 Pass/Fail
visordemo serve --host 192.168.2.100                   # web UI: http://127.0.0.1:8601
visordemo simulate --port 2006                         # 假 VISOR 伺服器(無實機開發用)
```

Library:

```python
from visordemo import Camera

with Camera("192.168.2.100") as cam:
    frame = cam.capture()          # TRG + GIM0
    print(frame.rows, frame.cols, frame.good)
    open("shot.png", "wb").write(frame.to_png())
```

## 換掉 qc-station 的 webcam

`photo.py` 的 `capture()` 已留 `camera_factory` 注入點,呼叫序列(context manager、`set_control`、`start_stream`、`stop_stream`)本套件全部相容,只差取像方法名稱:

```python
from functools import partial
from visordemo import Camera as VisorCamera

photo.capture("192.168.2.100", dst, camera_factory=VisorCamera)
# photo.py 內 read_jpeg() 一行改為:
#   frame = cam.read_png() if hasattr(cam, "read_png") else cam.read_jpeg()
# (VISOR 出灰階 PNG 而非 JPEG;副檔名建議跟著改 .png)
```

`set_control` 會 raise `NotImplementedError`(photo.py 原本就 try/except 跳過)——VISOR 的曝光、增益等參數屬於 job,在 SensoConfig 裡設定,不走這個介面。

## Web UI

`visordemo serve` 後開 <http://127.0.0.1:8601> :連續預覽(可調輪詢間隔)、單張擷取、下載影像、對焦(含自動對焦與即時 FOV 顯示)、快門/增益/自動曝光、job 切換。每個請求都是開連線-做-關連線,斷線自癒。

HTTP API(全部回 JSON,錯誤回 `{"ok":false,"error":...}`):

| Path | 說明 |
|---|---|
| `GET /snapshot.png` | 觸發 + 取像,回 PNG |
| `GET /api/info` | 對焦/FOV/快門/增益/job 一次全讀 |
| `GET /api/focus[?set=mm 或 auto=1]` | 讀/設/自動對焦 |
| `GET /api/shutter[?set=ms 或 auto=1]` | 讀/設/自動曝光 |
| `GET /api/gain[?set=x]` | 讀/設增益 |
| `GET /api/job[?set=n或名稱]` | 讀/切換 job |

## 已知限制與坑

- **ASCII 協定**:感測器的 telegram 格式須設為 ASCII(SensoConfig 出廠預設)。BINARY 格式未實作。
- **End-of-telegram**:若 SensoConfig 裡設定了結尾字元,建 `Camera(..., eot=b"\r\n")` 帶上,否則影像資料起點會錯位。預設無。
- **Bayer 彩色**:影像型別 3 做半解析度 demosaic(2x2 quad → 1 RGB 像素);黑白/彩色由感光元件硬體決定,黑白機種(GIM 回型別 0)不可能輸出彩色。
- **舊韌體 SST 數值語義不明**:實測一台舊韌體(GSI 不支援),`SST` 設快門時同一格式有的值正確、有的值差一個數量級(疑似解析規則不同於 2.10 手冊)。`set_shutter()` 靠讀回驗證擋掉錯誤結果,但某些目標值會直接回報失敗——舊韌體調曝光請改用 `auto_shutter()`(實測可用)或 SensoConfig。
- **機種支援度**:各 telegram 的可用性依 VISOR 機種/韌體而異(手冊 Availability 表);新機第一次先跑 `visordemo info` 和 `snapshot` 驗證。
- **`good=False` 不是錯誤**:那是感測器 job 的檢測判定(Pass/Fail),與取像成敗無關。
- 未實作(用不到就沒做):TRX/TRR/STI 進階觸發、檢測器參數 SPP/GPA、ROI SRP、校正設定 CSP、統計 RST、BINARY 協定。

已於實機驗證(2026-07,VISOR @ 192.168.2.111,舊韌體):trigger/snapshot(1440x1080 灰階)、GFC/SFC/AFC 對焦(50~1830mm 行程)、GJL/CJB job 切換、GSH 讀快門、ASH 自動曝光、GGA/SGA 增益、CGP 010 內參(焦距 12.119mm、pixel 3.449µm)。GSI 在該韌體不支援。

## 測試

```bash
python3 -m unittest discover -s tests -v   # 零硬體:協定單元測試 + simulator 端對端
```

## 授權

MIT — 林亞澤 Yaze Lin

---

- 原始碼 GitHub:<https://github.com/yazelin/visordemo>
- Facebook:<https://www.facebook.com/yaze.lin.gm>
- Buy Me a Coffee:<https://buymeacoffee.com/yazelin>
