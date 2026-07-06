# visordemo — SensoPart VISOR 影像擷取(library + CLI + web UI)

visordemo 是一個純 Python(零相依)的 SensoPart VISOR 視覺感測器影像擷取工具,同一套程式提供三種用法:當 **library** 匯入(`with Camera(host) as cam: ...`)、當 **CLI** 操作(`visordemo snapshot -o shot.png`)、或啟動內建 **web UI** 即時預覽。介面刻意做成與 [webcamdemo](https://github.com/yazelin/webcamdemo) 相容,消費端(如品檢站)把 `camera_factory` 換掉即可從 USB webcam 切換到 VISOR。

## 原理

VISOR 感測器的 request/response 通道(預設 TCP port 2006)支援 ASCII telegram:

- `TRG` — 觸發一次取像,回 `TRGP`(Pass)/`TRGF`(Fail)
- `GIMx` — Get Image(x:0=最後一張、1=最後 NG、2=最後 OK),回 15 bytes header(良否、影像型別、rows、cols)+ rows×cols 的 raw 8-bit 影像資料

visordemo 把 `TRG` + `GIM` 包成一次 `capture()`,raw 灰階直接以 stdlib zlib 編成 PNG 落地。依據官方 [VISOR Communications Manual 068-14859](https://www.sensopart.com/en/service/downloads/)(2024-04 版)。

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

`visordemo serve` 後開 <http://127.0.0.1:8601> :連續預覽(可調輪詢間隔)、單張擷取、下載目前影像。每張都是開連線-拍-關連線,斷線自癒。

## 已知限制與坑

- **ASCII 協定**:感測器的 telegram 格式須設為 ASCII(SensoConfig 出廠預設)。BINARY 格式未實作。
- **End-of-telegram**:若 SensoConfig 裡設定了結尾字元,建 `Camera(..., eot=b"\r\n")` 帶上,否則影像資料起點會錯位。預設無。
- **Bayer 彩色**:影像型別 3(Bayer BG)目前直接以灰階輸出 raw mosaic,未做 demosaic。單色機種(常見)不受影響。
- **機種支援度**:`GIM` 的可用性依 VISOR 機種/韌體而異,請對照該機型通訊手冊的 Availability 表;實機第一次先跑 `visordemo snapshot` 驗證。
- **未在實機驗證**:協定依官方手冊(068-14859-05 EN)撰寫並以內建 simulator 測試,尚未接過實體 VISOR。實機驗證清單:
  1. `visordemo trigger --host <ip>` — 應回 Pass。
  2. `visordemo snapshot --host <ip>` — 應存出解析度正確的 PNG。
  3. `visordemo serve --host <ip>` — 連續預覽畫面應隨現場變化。

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
