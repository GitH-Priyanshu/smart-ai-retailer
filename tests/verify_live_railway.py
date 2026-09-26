import time
import json
import httpx

url = "https://smart-ai-retailer-production.up.railway.app"

print("Waiting for Railway deployment with gemini-3.5-flash-lite...")
for i in range(40):
    try:
        r = httpx.get(url + "/v1/metadata", timeout=5)
        if r.status_code == 200 and r.json().get("model") == "gemini-3.5-flash-lite":
            print(f"Deployment detected live after {i*3}s!")
            break
    except Exception:
        pass
    time.sleep(3)
else:
    print("Proceeding with current live server...")

client = httpx.Client(base_url=url, timeout=30.0)

# 1. GET /v1/healthz
t0 = time.perf_counter()
r_health = client.get("/v1/healthz")
t_health = (time.perf_counter() - t0) * 1000

# 2. GET /v1/metadata
t0 = time.perf_counter()
r_meta = client.get("/v1/metadata")
t_meta = (time.perf_counter() - t0) * 1000

# 3. POST /v1/context (1 category, 1 merchant)
with open("dataset/categories/dentists.json", encoding="utf-8") as f:
    cat = json.load(f)
with open("dataset/merchants_seed.json", encoding="utf-8") as f:
    merchants_seed = json.load(f)["merchants"]
    merch = merchants_seed[0]

# Push fresh version or version 1
t0 = time.perf_counter()
r_cat = client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 2, "payload": cat})
if r_cat.status_code == 409:
    r_cat = client.post("/v1/context", json={"scope": "category", "context_id": "dentists", "version": 3, "payload": cat})
t_cat = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
r_merch = client.post("/v1/context", json={"scope": "merchant", "context_id": merch["merchant_id"], "version": 2, "payload": merch})
if r_merch.status_code == 409:
    r_merch = client.post("/v1/context", json={"scope": "merchant", "context_id": merch["merchant_id"], "version": 3, "payload": merch})
t_merch = (time.perf_counter() - t0) * 1000

# 4. POST /v1/tick with empty available_triggers
t0 = time.perf_counter()
r_tick = client.post("/v1/tick", json={"available_triggers": []})
t_tick = (time.perf_counter() - t0) * 1000

print("\n" + "=" * 80)
print("1. GET /v1/healthz")
print(f"Status Code: {r_health.status_code} | Latency: {t_health:.2f} ms")
print("Response JSON:")
print(json.dumps(r_health.json(), indent=2))

print("\n" + "=" * 80)
print("2. GET /v1/metadata")
print(f"Status Code: {r_meta.status_code} | Latency: {t_meta:.2f} ms")
print("Response JSON:")
print(json.dumps(r_meta.json(), indent=2))

print("\n" + "=" * 80)
print("3. POST /v1/context")
print(f"Category (dentists) -> Status Code: {r_cat.status_code} | Latency: {t_cat:.2f} ms")
print("Response JSON:")
print(json.dumps(r_cat.json(), indent=2))
print(f"Merchant ({merch['merchant_id']}) -> Status Code: {r_merch.status_code} | Latency: {t_merch:.2f} ms")
print("Response JSON:")
print(json.dumps(r_merch.json(), indent=2))

print("\n" + "=" * 80)
print("4. POST /v1/tick (empty available_triggers)")
print(f"Status Code: {r_tick.status_code} | Latency: {t_tick:.2f} ms")
print("Response JSON:")
print(json.dumps(r_tick.json(), indent=2))
