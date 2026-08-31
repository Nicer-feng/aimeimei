DEFAULT_FEATURE_FLAGS = {
    "selection_quote": True,
    "side_discussion": True,
}


def feature_flags(secrets_data):
    raw = (secrets_data or {}).get("feature_flags")
    if not isinstance(raw, dict):
        raw = {}
    return {key: bool(raw.get(key, default)) for key, default in DEFAULT_FEATURE_FLAGS.items()}


def feature_enabled(secrets_data, name):
    return bool(feature_flags(secrets_data).get(name))
