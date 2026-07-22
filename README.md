# Distributed Observability AI Copilot

AI copilot đọc log/trace/metric/resource utilization **thật** từ một cụm microservice đang chạy
([OpenTelemetry Demo "Astronomy Shop"](https://github.com/open-telemetry/opentelemetry-demo)) và trả
lời câu hỏi về hạ tầng qua giao diện chat:

- "Có gì bất thường trong khoảng thời gian này không?"
- "Có gì bất thường trong trace_id này không?"
- "Lỗi này là gì và cách fix ra sao?"
- ...cộng thêm health check, right-sizing, capacity planning — đây là một **analyst**, không chỉ
  là bộ phát hiện lỗi.

> Repo gồm 3 phần: **otel-demo** (cụm microservice mẫu để tạo dữ liệu telemetry thật) +
> **Grafana/Tempo/Loki/Prometheus** (nơi xem log/trace/metric bằng mắt) + **AI Copilot** (chatbot
> đọc cùng dữ liệu đó và trả lời bằng ngôn ngữ tự nhiên). Ba phần chạy song song, không phần nào
> thay thế phần nào — Grafana dùng để nhìn số liệu thô, chatbot dùng để hỏi nhanh "đang có chuyện
> gì".

## Hướng dẫn chạy — từng bước (dùng OpenRouter)

Project hỗ trợ nhiều LLM provider (`anthropic` / `deepseek` / `ollama`), nhưng hướng dẫn dưới đây
chỉ dùng **OpenRouter** (qua provider `deepseek`, trỏ base URL sang OpenRouter — xem giải thích ở
bước 5). Không cần tài khoản Anthropic hay cài Ollama.

### Bước 1 — Lấy API key OpenRouter

1. Vào https://openrouter.ai → **Sign in** (đăng nhập bằng Google/GitHub đều được, không cần thẻ
   để tạo tài khoản).
2. Vào https://openrouter.ai/keys → bấm **Create Key**, đặt tên bất kỳ (vd. `observability-ai`) →
   copy key, dạng `sk-or-v1-...` (chỉ hiện 1 lần, lưu lại ngay).
3. Vào https://openrouter.ai/settings/credits → **nạp credit** (tối thiểu vài đô là đủ demo).
   Bắt buộc — không có credit thì mọi câu hỏi trong chat sẽ lỗi `402 Payment Required` giữa chừng
   (đã từng gặp lỗi này khi hết credit trong lúc demo, xem `PROGRESS.md`). Kiểm tra lại
   credit trước khi demo/present.

### Bước 2 — Clone otel-demo (nguồn dữ liệu thật)

```bash
git clone --branch 2.2.0 https://github.com/open-telemetry/opentelemetry-demo otel-demo
```
Chốt version `2.2.0`, không dùng `main` (repo này build/test với bản đó). Chi tiết xem mục 3 bên dưới.

### Bước 3 — Bật docker compose (demo + Tempo/Loki/Grafana)

Chạy từ root repo, file demo phải liệt kê trước:
```bash
docker compose -f otel-demo/docker-compose.yml -f overrides/docker-compose.override.yml up -d
```
Đợi vài phút rồi kiểm tra: shop UI http://localhost:8080 → 200, Grafana
http://localhost:3000/api/health → 200, Prometheus http://localhost:9090/-/healthy, Loki
http://localhost:3100/ready, Tempo http://localhost:3200/ready.

### Bước 4 — Cài Python deps

Repo chưa có `requirements.txt`/`pyproject.toml` — cài thẳng vào user site-packages:
```bash
python3 -m pip install --user pydantic fastapi uvicorn requests pyyaml langgraph pytest anthropic openai
```
(thêm `--break-system-packages` nếu pip từ chối vì Python hệ thống bị khoá externally-managed).
Gói `openai` là bắt buộc dù không dùng OpenAI — provider `deepseek`/OpenRouter dùng chung SDK này
(OpenAI-compatible API).

### Bước 5 — Tạo `.env` với key OpenRouter

```bash
cp .env.example .env
```
Sửa các dòng sau trong `.env` (dán key lấy ở Bước 1 vào `DEEPSEEK_API_KEY`):
```bash
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-or-v1-...............................
DEEPSEEK_MODEL=deepseek/deepseek-chat
DEEPSEEK_BASE_URL=https://openrouter.ai/api/v1
```
`deepseek` provider vốn gọi thẳng API DeepSeek gốc, nhưng vì dùng OpenAI-compatible SDK nên chỉ
cần đổi `DEEPSEEK_BASE_URL` sang OpenRouter + đổi `DEEPSEEK_MODEL` thành tên model kiểu OpenRouter
(`deepseek/deepseek-chat`) là dùng được OpenRouter key mà không cần sửa code. Có thể đổi
`DEEPSEEK_MODEL` sang model OpenRouter khác nếu muốn (xem danh sách tại
https://openrouter.ai/models).

Load `.env` vào shell — **bắt buộc mỗi lần mở terminal mới**, `.env` không tự nạp:
```bash
set -a && source .env && set +a
```

### Bước 6 — Chạy chatbot và hỏi thử

```bash
python3 -m interfaces.dashboard.app
```
Mở http://localhost:8500, gõ câu hỏi, vd. "How is the system doing right now?" — nếu trả lời về
mà không có lỗi 500/402 nghĩa là OpenRouter key + docker stack đã chạy đúng.

Sau bước này, xem tiếp mục 1-5 bên dưới để biết Grafana, cách tạo lỗi demo (chaos), và slide
thuyết trình.

---

## Kiến trúc tổng quan

```
otel-demo (docker compose)          overrides/ (docker compose)
  các service của shop + load gen     Tempo (trace), Loki (log, OTLP native)
  Kafka, flagd (feature flags)        Prometheus giữ nguyên, Grafana +datasource Tempo/Loki
              \                          /
               \                        /
                v                      v
        retrieval/ (client đọc log/metric/trace + che PII)
                      |
              detection/ (bộ phát hiện bất thường bằng Python thuần, không dùng LLM:
                          error rate, latency, queue backlog, throughput, cpu/mem vs limit)
                      |
              agents/ (LangGraph orchestrator: extract → RCA → fix,
                       LLM_PROVIDER: anthropic | deepseek | ollama)
                      |
          interfaces/dashboard (FastAPI chat UI, localhost:8500)
```

Lỗi được "tiêm" vào hệ thống qua **flagd feature flags** có sẵn trong OTel demo (không viết code
chaos can thiệp vào các service của demo). Xem phần "Tạo kịch bản lỗi (chaos)" bên dưới.

---

## 1. AI Chatbot — giao diện chính, ưu tiên demo

**Ở đâu:** `interfaces/dashboard/` (FastAPI app + `static/index.html`), chạy ở
**http://localhost:8500**.

**Chạy:**
```bash
set -a && source .env && set +a     # bắt buộc — xem "Hướng dẫn chạy — từng bước" ở đầu file
python3 -m interfaces.dashboard.app
```
Mở http://localhost:8500 → là màn hình chat, gõ câu hỏi rồi Enter. Mỗi câu hỏi chạy qua toàn bộ
pipeline LangGraph (lấy dữ liệu → phát hiện bất thường → LLM phân tích → trả lời), câu trả lời
luôn bám vào số liệu thật lấy từ Loki/Tempo/Prometheus (không được bịa số).

Có thể hỏi bất kỳ lúc nào, kể cả khi hệ thống đang bình thường:
- "How is the system doing right now?"
- "Is the payment service over-provisioned?"
- "If traffic tripled, which service saturates first?"

Khi có chaos đang chạy (xem phần 3), hỏi tiếp kiểu:
- "What's wrong with checkout right now?"
- "Which trace_id shows this failure?"
- "What should I do to fix it?"

**Lưu ý quan trọng khi chạy thử:** `.env` **không tự động được load** bởi app — chỉ
`chaos/flags.py` tự đọc `.env`, còn `interfaces.dashboard.app`, `scripts.run_demo`,
`set -a && source .env && set +a` trước, mỗi lần mở terminal mới.


---

## 2. Grafana — nhìn số liệu thô

**Ở đâu:** ship kèm otel-demo, đã được thêm datasource Tempo + Loki qua `overrides/grafana/`.
Chạy ở **http://localhost:3000** (đăng nhập xem `overrides/` hoặc mặc định `admin/admin`).

Dashboard đáng chú ý: **`overrides/grafana/dashboards/ai-copilot.json`** — dashboard riêng cho
copilot, có ô chọn `$service` (dropdown, tự động load danh sách service từ metrics) và các panel:
- **Request rate** theo service đang chọn
- **Error rate** theo service đang chọn
- **p95 latency** theo service đang chọn
- **Requests 30 phút gần nhất** (dạng cột)
- **Logs 30 phút gần nhất** của service đang chọn (đọc thẳng từ Loki)

Dùng dashboard này để đối chiếu bằng mắt với câu trả lời của chatbot — ví dụ chatbot báo
`payment` đang error_rate_spike thì mở dashboard, chọn `service=payment`, xem panel Error rate có
khớp không.

Các panel khác (log viewer chung, trace search...) nằm trong cùng thư mục
`overrides/grafana/dashboards/`.

---

## 3. otel-demo — nguồn dữ liệu thật

**Ở đâu:** thư mục `otel-demo/` — đây là **git clone** của
[opentelemetry-demo](https://github.com/open-telemetry/opentelemetry-demo), **không** được commit
vào git của repo này (xem `.gitignore`). Nếu thư mục trống, clone lại:

```bash
git clone --branch 2.2.0 https://github.com/open-telemetry/opentelemetry-demo otel-demo
```
(chốt version `2.2.0`, không dùng `main`, vì repo này được build và test với bản đó.)

Đây là một shop giả lập (Astronomy Shop) gồm hơn chục microservice (frontend, cart, checkout,
payment, ad, currency, shipping...) + load generator tự sinh traffic + Kafka + **flagd**
(feature-flag server dùng để tiêm lỗi, xem phần 4).

**Bật toàn bộ stack** (demo + Tempo/Loki override — luôn chạy từ root repo, file demo phải liệt kê
trước vì đường dẫn tương đối trong file override tính theo file demo):
```bash
docker compose -f otel-demo/docker-compose.yml -f overrides/docker-compose.override.yml up -d
```

Kiểm tra đã lên đủ:
| Thành phần | Kiểm tra |
|---|---|
| Shop UI | http://localhost:8080 → 200 |
| Grafana | http://localhost:3000/api/health → 200 |
| Prometheus | http://localhost:9090/-/healthy |
| Loki | http://localhost:3100/ready |
| Tempo | http://localhost:3200/ready |

Loki/Tempo có thể trả `503 "waiting for 15s after being ready"` ngay sau khi mới bật — bình
thường, chỉ lo nếu sau 1 phút vẫn còn 503.

**Để load generator chạy khoảng ~15 phút** trước khi demo các câu hỏi kiểu "is this
over-provisioned?" — câu trả lời right-sizing cần lịch sử utilization thật, chạy mới bật thì chưa
đủ dữ liệu.

---

## 4. Tạo kịch bản lỗi (chaos) để demo

Lỗi = flag có sẵn trong `otel-demo/src/flagd/demo.flagd.json`, được `chaos/flags.py` sửa trực tiếp
(flagd tự hot-reload file, không cần restart).

**Cách dễ nhất — Chaos control panel** (UI có nút bấm, không cần terminal thứ hai khi demo):
```bash
python3 -m interfaces.chaos_panel.app
```
Mở **http://localhost:8600** → bấm nút để start/stop từng kịch bản, và có nút **Reset** để dọn
sạch môi trường (archive lịch sử cũ vào `results/archive/<timestamp>/`, tắt hết flag) trước một
lượt demo mới.

**Cách dòng lệnh** (chạy 1 kịch bản, tự đợi rồi tự tắt flag):
```bash
python3 -m chaos.scenarios <name> --duration 120
```

4 kịch bản:
| Tên | Flag trong flagd | Bất thường mong đợi | Loại lỗi |
|---|---|---|---|
| `payment_failure` | `paymentFailure` → 100% | error_rate_spike | service_failure |
| `payment_outage` | `paymentUnreachable` → on | span_gap + error_rate_spike | broken_trace / timeout |
| `queue_backlog` | `kafkaQueueProblems` → on | queue_anomaly | message_loss |
| `overload` | `adHighCpu` → on | latency_spike (+ throughput_drop) | resource_exhaustion |

`payment_failure`/`payment_outage`/`queue_backlog` cần traffic thật đi qua checkout mới thấy hiệu
ứng rõ, nên nếu traffic thấp thì tăng `--duration` lên ~180s thay vì mặc định 120s.

Ctrl+C giữa chừng sẽ tự tắt hết flag (an toàn, không để demo bị kẹt ở trạng thái lỗi).

---

## 5. Kịch bản trình diễn (presentation)

**Slide deck kiến trúc:** `presentation/` — deck 18 slide dạng PPTX, điều hướng bằng phím, nội dung
lấy từ chính source code + `PROGRESS.md` của repo này (dùng khi trình bày kiến trúc cho người kỹ
thuật, tách biệt với demo chat trực tiếp ở trên).
```bash
cd presentation
npm install     # zero dependency, không có gì để cài
npm run dev     # chạy server tĩnh built-in (server.js, chỉ dùng stdlib Node)
```
Mở **http://localhost:5174**. Điều khiển: `→`/`Space` slide kế, `←` slide trước, `Home`/`End` về
đầu/cuối, click mép trái/phải hoặc chấm tiến trình ở dưới để nhảy slide.

---

## Chạy test

```bash
# nhanh (vẫn gọi Loki/Tempo/Prometheus thật để lấy số liệu, ~2s)
python3 -m pytest -q --ignore=tests/test_detection_scenarios.py -m "not e2e"

# chậm, chạy chaos thật trên stack live (~15+ phút)
python3 -m pytest tests/test_detection_scenarios.py -v -s

# chậm, chaos thật + gọi LLM thật (~8 phút, cần LLM credential hoạt động)
python3 -m pytest tests/test_e2e_scenario.py -v -s -m e2e
```
Lưu ý: `pytest.ini` chỉ *đăng ký* marker `e2e`, không tự loại trừ nó, và
`tests/test_detection_scenarios.py` chạy chaos thật dù không gắn marker `e2e` — chạy `pytest` trần
không tham số sẽ treo 15+ phút, **không phải** lệnh test nhanh dù tên file trông vô hại.

---

## Vị trí các thành phần trong repo

```
otel-demo/          clone của opentelemetry-demo (không commit vào git repo này)
overrides/           docker-compose.override.yml + config Tempo/Loki/Grafana
  grafana/dashboards/ai-copilot.json   ← dashboard Grafana riêng cho copilot (mục 2)
chaos/               flags.py (sửa demo.flagd.json), scenarios.py (chạy kịch bản có timer)
retrieval/           client đọc log/metric/trace + che PII — mọi dữ liệu ra khỏi đây đã được mask
detection/           bộ phát hiện bất thường, Python thuần, không LLM
agents/              schema, LLM client (anthropic/deepseek/ollama), web search, context builder,
                     analyst, LangGraph orchestrator
interfaces/dashboard     AI chatbot (FastAPI + UI tĩnh), localhost:8500 — mục 1
interfaces/chaos_panel   Chaos control panel, localhost:8600 — mục 4
results/             analysis_history.jsonl + hội thoại đã lưu (+ archive/ khi reset chaos panel)
scripts/             run_demo.py (kịch bản demo), scheduled_scan.py (scanner nền)
tests/               pytest — phần lớn nhanh, 2 file còn lại chạy chaos live/chậm (xem "Chạy test")
docs/                DEMO_SCRIPT.md (mục 5), PHASE1-5.md (spec) + EXPECTED-PHASE1-5.md (checklist)
presentation/        slide deck kiến trúc (Node, zero-dep static server), xem mục 5
```

## Lệnh Claude Code có sẵn

- `/phase <n>` — làm việc theo checklist của 1 phase.
- `/verify <n>` — đối chiếu 1 phase với file EXPECTED tương ứng (chỉ kiểm tra, không sửa).
- `/scenario <name>` — chạy 1 kịch bản chaos end-to-end, in ra detection → câu trả lời của analyst.
- `/handoff` — cập nhật PROGRESS.md từ git state cuối phiên làm việc.
