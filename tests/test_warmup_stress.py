import asyncio
import glob
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

BASE_URL = os.getenv("BOT_URL", "https://smart-ai-retailer-production.up.railway.app").rstrip("/")

async def push_item(client: httpx.AsyncClient, semaphore: asyncio.Semaphore, scope: str, context_id: str, version: int, payload: dict):
    body = {
        "scope": scope,
        "context_id": context_id,
        "version": version,
        "payload": payload,
        "delivered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    url = f"{BASE_URL}/v1/context"
    async with semaphore:
        t0 = time.time()
        try:
            resp = await client.post(url, json=body, timeout=15.0)
            latency = (time.time() - t0) * 1000
            data = resp.json() if resp.status_code in (200, 400, 409) else None
            return {
                "scope": scope,
                "context_id": context_id,
                "status_code": resp.status_code,
                "latency_ms": latency,
                "accepted": data.get("accepted") if data else False,
                "reason": data.get("reason") if data else None,
                "error": None if resp.status_code in (200, 409) else f"HTTP {resp.status_code}: {resp.text[:100]}",
            }
        except Exception as e:
            latency = (time.time() - t0) * 1000
            return {
                "scope": scope,
                "context_id": context_id,
                "status_code": 0,
                "latency_ms": latency,
                "accepted": False,
                "reason": "exception",
                "error": str(e),
            }

async def main():
    root = Path(__file__).resolve().parent.parent
    
    # 1. Load Categories
    categories = []
    cat_files = glob.glob(str(root / "dataset" / "categories" / "*.json"))
    for f in cat_files:
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
            slug = data.get("slug", Path(f).stem)
            categories.append((slug, data))
            
    # 2. Load Merchants
    merchants = []
    merchant_files = glob.glob(str(root / "expanded" / "merchants" / "*.json"))
    for f in merchant_files:
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
            mid = data.get("merchant_id", Path(f).stem)
            merchants.append((mid, data))
            
    # 3. Load Customers
    customers = []
    customer_files = glob.glob(str(root / "expanded" / "customers" / "*.json"))
    for f in customer_files:
        with open(f, encoding="utf-8") as fp:
            data = json.load(fp)
            cid = data.get("customer_id", Path(f).stem)
            customers.append((cid, data))

    print(f"=== WARMUP STRESS TEST ===")
    print(f"Target URL: {BASE_URL}")
    print(f"Loaded: {len(categories)} categories, {len(merchants)} merchants, {len(customers)} customers")
    print(f"Total pushes to execute: {len(categories) + len(merchants) + len(customers)}")

    semaphore = asyncio.Semaphore(25)  # 25 concurrent connections
    limits = httpx.Limits(max_keepalive_connections=30, max_connections=50)

    start_time = time.time()
    async with httpx.AsyncClient(limits=limits) as client:
        tasks = []
        for slug, cat in categories:
            tasks.append(push_item(client, semaphore, "category", slug, 1, cat))
        for mid, m in merchants:
            tasks.append(push_item(client, semaphore, "merchant", mid, 1, m))
        for cid, c in customers:
            tasks.append(push_item(client, semaphore, "customer", cid, 1, c))

        results = await asyncio.gather(*tasks)

        # Health check
        health_resp = await client.get(f"{BASE_URL}/v1/healthz", timeout=10.0)
        health_data = health_resp.json()

    total_time = time.time() - start_time

    # Tally results
    status_200 = [r for r in results if r["status_code"] == 200]
    status_409 = [r for r in results if r["status_code"] == 409]
    failures = [r for r in results if r["status_code"] not in (200, 409)]

    print(f"\n--- PUSH RESULTS ---")
    print(f"Total Completed: {len(results)} in {total_time:.2f}s (avg {(total_time/len(results))*1000:.1f}ms/push)")
    print(f"200 OK (New additions): {len(status_200)}")
    print(f"409 Conflict (Already stored v1): {len(status_409)}")
    print(f"Failures / Timeouts: {len(failures)}")

    if status_409:
        print(f"\n409 details (expected for items pushed during prior runs):")
        for r in status_409[:10]:
            print(f"  - {r['scope']}/{r['context_id']}: {r['reason']}")
        if len(status_409) > 10:
            print(f"  ... and {len(status_409) - 10} more")

    if failures:
        print(f"\nFAILURES:")
        for r in failures:
            print(f"  - {r['scope']}/{r['context_id']}: {r['error']}")

    print(f"\n--- HEALTHZ CONFIRMATION ---")
    print(json.dumps(health_data, indent=2))
    
    contexts = health_data.get("contexts_loaded", {})
    cat_ok = contexts.get("category") == 5
    merch_ok = contexts.get("merchant") == 50
    cust_ok = contexts.get("customer") == 200

    print(f"\nValidation:")
    print(f"  Category: {contexts.get('category')} / 5 {'[PASS]' if cat_ok else '[FAIL]'}")
    print(f"  Merchant: {contexts.get('merchant')} / 50 {'[PASS]' if merch_ok else '[FAIL]'}")
    print(f"  Customer: {contexts.get('customer')} / 200 {'[PASS]' if cust_ok else '[FAIL]'}")

    if cat_ok and merch_ok and cust_ok and not failures:
        print("\n>>> SECTION 2 WARMUP STRESS TEST: ALL PASSED <<<")
    else:
        print("\n>>> SECTION 2 WARMUP STRESS TEST: COMPLETED WITH WARNINGS/FAILURES <<<")

if __name__ == "__main__":
    asyncio.run(main())
