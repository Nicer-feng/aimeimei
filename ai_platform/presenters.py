def public_model(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "provider": row["provider"],
        "base_url": row["base_url"],
        "model": row["model"],
        "system_prompt": row["system_prompt"],
        "supports_vision": bool(row["supports_vision"]) if "supports_vision" in row.keys() else False,
        "supports_native_web_search": bool(row["supports_native_web_search"]) if "supports_native_web_search" in row.keys() else False,
        "enabled": bool(row["enabled"]),
        "input_price_per_million": float(row["input_price_per_million"] or 0) if "input_price_per_million" in row.keys() else 0,
        "output_price_per_million": float(row["output_price_per_million"] or 0) if "output_price_per_million" in row.keys() else 0,
        "cost_enabled": bool(row["cost_enabled"]) if "cost_enabled" in row.keys() else False,
        "cost_note": row["cost_note"] if "cost_note" in row.keys() else "",
        "has_api_key": bool(row["api_key"].strip()),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def private_model(row):
	return public_model(row)


def ai_user_public(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def conversation_row(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "model_id": row["model_id"],
        "model_name": row["model_name"],
        "model": row["model"],
        "supports_vision": bool(row["supports_vision"]) if "supports_vision" in row.keys() else False,
        "supports_native_web_search": bool(row["supports_native_web_search"]) if "supports_native_web_search" in row.keys() else False,
        "pinned": bool(row["pinned"]) if "pinned" in row.keys() else False,
        "pinned_at": row["pinned_at"] if "pinned_at" in row.keys() else 0,
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


def visible_user_question(content):
    value = str(content or "").strip()
    prefix = "以下是用户从当前会话中引用的内容："
    if not value.startswith(prefix):
        return value
    for marker in ("\n\n用户的新问题：", "\n用户的新问题："):
        _, separator, question = value.rpartition(marker)
        if separator and question.strip():
            return question.strip()
    return value


def side_discussion_public(row):
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "source_message_id": row["source_message_id"],
        "source_role": row["source_role"],
        "source_created_at": row["source_created_at"],
        "selected_text": row["selected_text"],
        "model_id": row["model_id"],
        "model_name": row["model_name"] if "model_name" in row.keys() else "",
        "model": row["model"] if "model" in row.keys() else "",
        "title": row["title"],
        "status": row["status"],
        "message_count": int(row["message_count"] or 0) if "message_count" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def side_discussion_message_public(row):
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "reasoning_content": row["reasoning_content"],
        "created_at": row["created_at"],
        "usage": {
            "prompt_tokens": int(row["input_tokens"] or 0),
            "completion_tokens": int(row["output_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "estimated_cost": float(row["estimated_cost"] or 0),
        },
    }


def estimate_profile_tokens(text) -> int:
    value = str(text or "")
    cjk = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    other = max(0, len(value) - cjk)
    return max(0, int(cjk * 0.8 + other / 4))


def user_profile_row(row):
    title = row["title"]
    content = row["content"]
    text = f"{title}\n{content}"
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": title,
        "content": content,
        "type": row["type"],
        "sort_order": row["sort_order"],
        "enabled": bool(row["enabled"]),
        "char_count": len(text),
        "token_estimate": estimate_profile_tokens(text),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def profile_totals(rows):
    enabled_rows = [row for row in rows if bool(row["enabled"])]
    all_text = "\n".join(f"{row['title']}\n{row['content']}" for row in enabled_rows)
    return {
        "enabled_count": len(enabled_rows),
        "total_count": len(rows),
        "char_count": len(all_text),
        "token_estimate": estimate_profile_tokens(all_text),
    }


def build_user_profile_context(rows):
    enabled_rows = [row for row in rows if bool(row["enabled"]) and str(row["content"] or "").strip()]
    if not enabled_rows:
        return ""
    parts = ["用户长期档案："]
    for row in enabled_rows:
        title = str(row["title"] or "").strip() or "未命名"
        content = str(row["content"] or "").strip()
        parts.append(f"【{title}】\n{content}")
    return "\n\n".join(parts)


def prompt_template_row(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def favorite_row(row):
    archived = bool(row["conversation_archived"]) if "conversation_archived" in row.keys() else False
    live_title = row["live_conversation_title"] if "live_conversation_title" in row.keys() else ""
    original_title = row["conversation_title"]
    return {
        "id": row["id"],
        "message_id": row["message_id"],
        "conversation_id": row["conversation_id"],
        "conversation_title": "原会话已删除" if archived or not live_title else live_title,
        "original_conversation_title": original_title,
        "role": row["role"],
        "content": row["content"],
        "message_created_at": row["message_created_at"],
        "created_at": row["created_at"],
    }


def media_task_public(row):
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "file_size": row["file_size"],
        "task_id": row["task_id"],
        "task_key": row["task_key"],
        "source_language": row["source_language"],
        "status": row["status"],
        "transcript_text": row["transcript_text"],
        "summary_text": row["summary_text"],
        "outline_text": row["outline_text"],
        "enhanced_summary": row["enhanced_summary"],
        "key_points": row["key_points"],
        "mindmap_text": row["mindmap_text"],
        "copywriting_text": row["copywriting_text"],
        "ai_outputs_json": row["ai_outputs_json"],
        "conversation_id": row["conversation_id"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def cat_user_public(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "avatar_url": row["avatar_url"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def cat_public(row):
    keys = set(row.keys())
    return {
        "id": row["id"],
        "owner_user_id": row["owner_user_id"],
        "name": row["name"],
        "avatar_url": row["avatar_url"],
        "breed": row["breed"],
        "gender": row["gender"],
        "birthday": row["birthday"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "post_count": int(row["post_count"] or 0) if "post_count" in keys else 0,
        "owner": {
            "id": row["owner_user_id"],
            "username": row["owner_username"],
            "nickname": row["owner_nickname"],
            "avatar_url": row["owner_avatar_url"],
        }
        if "owner_username" in keys
        else None,
    }


def cat_post_card(row):
    keys = set(row.keys())
    cat = None
    if "cat_id" in keys and row["cat_id"] and "cat_name" in keys and row["cat_name"]:
        cat = {
            "id": row["cat_id"],
            "name": row["cat_name"] or "",
            "avatar_url": row["cat_avatar_url"] or "",
            "breed": row["cat_breed"] or "",
            "gender": row["cat_gender"] or "",
            "birthday": row["cat_birthday"] or "",
            "description": row["cat_description"] or "",
        }
    return {
        "id": row["id"],
        "cat_id": row["cat_id"] if "cat_id" in keys else "",
        "cat": cat,
        "title": row["title"],
        "content": row["content"],
        "cover_url": row["cover_url"] or "",
        "image_count": int(row["image_count"] or 0),
        "like_count": int(row["like_count"] or 0) if "like_count" in keys else 0,
        "comment_count": int(row["comment_count"] or 0) if "comment_count" in keys else 0,
        "liked_by_me": bool(row["liked_by_me"]) if "liked_by_me" in keys else False,
        "created_at": row["created_at"],
        "author": {
            "id": row["user_id"],
            "username": row["username"],
            "nickname": row["nickname"],
            "avatar_url": row["avatar_url"],
        },
    }


def cat_comment_public(row):
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "author_type": row["actor_type"],
        "author_name": row["actor_name"],
        "content": row["content"],
        "created_at": row["created_at"],
    }
