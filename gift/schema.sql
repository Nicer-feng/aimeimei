CREATE TABLE IF NOT EXISTS gift_recipients (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 nickname TEXT NOT NULL DEFAULT '', gender TEXT NOT NULL DEFAULT '', birthday TEXT,
 approximate_age_months INTEGER, age_recorded_at TEXT, relationship TEXT NOT NULL DEFAULT '',
 clothing_size TEXT NOT NULL DEFAULT '', shoe_size TEXT NOT NULL DEFAULT '', allergies TEXT NOT NULL DEFAULT '',
 food_preferences TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', avatar TEXT,
 monthly_budget INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 UNIQUE(id,user_id), CHECK(monthly_budget IS NULL OR monthly_budget>=0)
);
CREATE TABLE IF NOT EXISTS gift_categories (
 id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), parent_id TEXT REFERENCES gift_categories(id),
 name TEXT NOT NULL, level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 3), sort_order INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS gift_category_path ON gift_categories(COALESCE(user_id,''),COALESCE(parent_id,''),name);
CREATE TABLE IF NOT EXISTS gift_assets (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), filename TEXT NOT NULL, mime_type TEXT NOT NULL,
 file_size INTEGER NOT NULL, oss_key TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, purpose TEXT NOT NULL,
 created_at INTEGER NOT NULL, UNIQUE(id,user_id)
);
CREATE TABLE IF NOT EXISTS gift_items (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, recipient_id TEXT NOT NULL, product_name TEXT NOT NULL,
 brand TEXT NOT NULL DEFAULT '', specification TEXT NOT NULL DEFAULT '', category_id TEXT REFERENCES gift_categories(id),
 category_level1 TEXT NOT NULL DEFAULT '', category_level2 TEXT NOT NULL DEFAULT '', category_level3 TEXT NOT NULL DEFAULT '',
 price INTEGER, quantity INTEGER, total_price INTEGER, purchase_date TEXT, purchase_month TEXT,
 source TEXT NOT NULL DEFAULT '', product_image TEXT, order_image TEXT, product_url TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', ai_generated INTEGER NOT NULL DEFAULT 0, import_entry_id TEXT,
 recognition_task_id TEXT, recognition_item_index INTEGER,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 FOREIGN KEY(recipient_id,user_id) REFERENCES gift_recipients(id,user_id),
 FOREIGN KEY(product_image,user_id) REFERENCES gift_assets(id,user_id),
 FOREIGN KEY(order_image,user_id) REFERENCES gift_assets(id,user_id),
 FOREIGN KEY(recognition_task_id,user_id) REFERENCES gift_recognition_tasks(id,user_id),
 UNIQUE(user_id,recognition_task_id,recognition_item_index),
 CHECK(price IS NULL OR price>=0),CHECK(quantity IS NULL OR quantity>0),CHECK(total_price IS NULL OR total_price>=0)
);
CREATE INDEX IF NOT EXISTS gift_item_timeline ON gift_items(user_id,recipient_id,purchase_month,purchase_date);
CREATE TABLE IF NOT EXISTS gift_recipient_profiles_history (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, recipient_id TEXT NOT NULL, clothing_size TEXT NOT NULL DEFAULT '',
 shoe_size TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', recorded_at TEXT NOT NULL,
 FOREIGN KEY(recipient_id,user_id) REFERENCES gift_recipients(id,user_id)
);
CREATE TABLE IF NOT EXISTS gift_purchase_marks (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,recipient_id TEXT NOT NULL,category_id TEXT NOT NULL REFERENCES gift_categories(id),
 purchase_month TEXT NOT NULL,import_batch_id TEXT NOT NULL,
 FOREIGN KEY(recipient_id,user_id) REFERENCES gift_recipients(id,user_id),UNIQUE(user_id,recipient_id,category_id,purchase_month)
);
CREATE TABLE IF NOT EXISTS gift_import_batches (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,recipient_id TEXT NOT NULL,file_hash TEXT NOT NULL,
 payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'preview',created_at INTEGER NOT NULL,
 FOREIGN KEY(recipient_id,user_id) REFERENCES gift_recipients(id,user_id),UNIQUE(user_id,recipient_id,file_hash)
);
CREATE TABLE IF NOT EXISTS gift_recognition_tasks (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,asset_id TEXT NOT NULL,model_id TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending',result TEXT NOT NULL DEFAULT '{}',ocr_text TEXT NOT NULL DEFAULT '',
 request_id TEXT NOT NULL DEFAULT '',usage_json TEXT NOT NULL DEFAULT '{}',error_message TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,
 FOREIGN KEY(asset_id,user_id) REFERENCES gift_assets(id,user_id),UNIQUE(id,user_id)
);
CREATE TABLE IF NOT EXISTS gift_confirmation_batches (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,request_key TEXT NOT NULL,payload_hash TEXT NOT NULL,result TEXT NOT NULL,
 created_at INTEGER NOT NULL,UNIQUE(user_id,request_key)
);
