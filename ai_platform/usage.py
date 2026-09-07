from .runtime import date_text_from_ts, now


def message_token_usage(row):
    prompt_tokens = int(row["prompt_tokens"] or 0) if "prompt_tokens" in row.keys() else 0
    completion_tokens = (
        int(row["completion_tokens"] or 0) if "completion_tokens" in row.keys() else 0
    )
    total_tokens = int(row["total_tokens"] or 0) if "total_tokens" in row.keys() else 0
    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens
    estimated_cost = float(row["estimated_cost"] or 0) if "estimated_cost" in row.keys() else 0.0
    cached_tokens = int(row["cached_tokens"] or 0) if "cached_tokens" in row.keys() else 0
    cache_creation_tokens = (
        int(row["cache_creation_tokens"] or 0)
        if "cache_creation_tokens" in row.keys()
        else 0
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
        "cached_tokens": cached_tokens,
        "cache_creation_tokens": cache_creation_tokens,
    }


def parse_usage_tokens(usage):
    if not isinstance(usage, dict):
        return (0, 0, 0)

    def read_int(*keys):
        for key in keys:
            value = usage.get(key)
            if value is None:
                continue
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    prompt_tokens = read_int("prompt_tokens", "input_tokens")
    completion_tokens = read_int("completion_tokens", "output_tokens")
    total_tokens = read_int("total_tokens")
    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens
    return (prompt_tokens, completion_tokens, total_tokens)

def parse_usage_cache_tokens(usage):
    """Read OpenAI-compatible cache metrics without changing total-token accounting."""
    if not isinstance(usage, dict):
        return (0, 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details")
    details = details if isinstance(details, dict) else {}

    def read_int(*keys):
        for source in (details, usage):
            for key in keys:
                value = source.get(key)
                if value is None:
                    continue
                try:
                    return max(0, int(value))
                except (TypeError, ValueError):
                    continue
        return 0

    return (
        read_int("cached_tokens", "cache_read_input_tokens"),
        read_int("cache_creation_input_tokens", "cache_creation_tokens"),
    )



def parse_price(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    return min(number, 1000000.0)


def estimate_request_cost(prompt_tokens, completion_tokens, input_price, output_price, enabled=True):
    if not enabled:
        return 0.0
    cost = (max(0, int(prompt_tokens or 0)) / 1000000.0 * parse_price(input_price)) + (
        max(0, int(completion_tokens or 0)) / 1000000.0 * parse_price(output_price)
    )
    return round(cost, 8)


def add_daily_usage(
    conn, user_id, timestamp, prompt_tokens, completion_tokens, total_tokens, estimated_cost,
    cached_tokens=0, cache_creation_tokens=0,
):
    usage_date = date_text_from_ts(timestamp)
    ts = now()
    conn.execute(
        """
        INSERT INTO daily_usage
        (user_id, date, request_count, input_tokens, output_tokens, total_tokens, estimated_cost,
         cached_tokens, cache_creation_tokens, updated_at)
        VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
          request_count=request_count+1,
          input_tokens=input_tokens+excluded.input_tokens,
          output_tokens=output_tokens+excluded.output_tokens,
          total_tokens=total_tokens+excluded.total_tokens,
          cached_tokens=cached_tokens+excluded.cached_tokens,
          cache_creation_tokens=cache_creation_tokens+excluded.cache_creation_tokens,
          estimated_cost=estimated_cost+excluded.estimated_cost,
          updated_at=excluded.updated_at
        """,
        (
            user_id,
            usage_date,
            max(0, int(prompt_tokens or 0)),
            max(0, int(completion_tokens or 0)),
            max(0, int(total_tokens or 0)),
            float(estimated_cost or 0),
            max(0, int(cached_tokens or 0)),
            max(0, int(cache_creation_tokens or 0)),
            ts,
        ),
    )
