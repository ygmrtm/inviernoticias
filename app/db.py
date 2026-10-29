import os
import sqlite3
import json
import time
from typing import Optional, List, Dict, Any
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).parent.parent / "inviernoticias.db"
DB_PATH = os.getenv("DATABASE_PATH", str(DEFAULT_DB_PATH))

def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id INTEGER,
                guid TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                pub_date DATETIME,
                content TEXT,
                analysis TEXT,
                notion_page_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Insert default feed for El Deforma if not exists
        deforma_url = "https://eldeforma.com/feed/"
        cursor.execute("SELECT id FROM feeds WHERE url = ?", (deforma_url,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO feeds (url, name) VALUES (?, ?)", (deforma_url, "El Deforma"))
        conn.commit()
    finally:
        conn.close()

# Auto-initialize on import so tables are always guaranteed ready
init_db()

def get_feeds() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM feeds ORDER BY created_at DESC;")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def get_feed_by_id(feed_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM feeds WHERE id = ?;", (feed_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def add_feed(url: str, name: str) -> int:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO feeds (url, name) VALUES (?, ?);", (url, name))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def delete_feed(feed_id: int) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM feeds WHERE id = ?;", (feed_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def add_article(feed_id: int, guid: str, title: str, link: str, pub_date: str, content: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO articles (feed_id, guid, title, link, pub_date, content)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (feed_id, guid, title, link, pub_date, content))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_articles(limit: int = 20, offset: int = 0, feed_id: Optional[int] = None, has_analysis: Optional[bool] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT a.*, f.name as feed_name FROM articles a LEFT JOIN feeds f ON a.feed_id = f.id"
        conditions = []
        params = []

        if feed_id is not None:
            conditions.append("a.feed_id = ?")
            params.append(feed_id)

        if has_analysis is not None:
            if has_analysis:
                conditions.append("a.analysis IS NOT NULL")
            else:
                conditions.append("a.analysis IS NULL")

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += " ORDER BY a.pub_date DESC, a.id DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        articles = []
        for row in rows:
            d = dict(row)
            if d.get("analysis"):
                try:
                    d["analysis_obj"] = json.loads(d["analysis"])
                except Exception:
                    d["analysis_obj"] = None
            else:
                d["analysis_obj"] = None
            articles.append(d)
        return articles
    finally:
        conn.close()

def get_article_by_id(article_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.*, f.name as feed_name 
            FROM articles a 
            LEFT JOIN feeds f ON a.feed_id = f.id 
            WHERE a.id = ?;
        """, (article_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("analysis"):
            try:
                d["analysis_obj"] = json.loads(d["analysis"])
            except Exception:
                d["analysis_obj"] = None
        else:
            d["analysis_obj"] = None
        return d
    finally:
        conn.close()

def update_article_analysis(article_id: int, analysis_dict: dict) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE articles SET analysis = ? WHERE id = ?;",
            (json.dumps(analysis_dict, ensure_ascii=False), article_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def update_article_notion_page(article_id: int, notion_page_id: str) -> bool:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE articles SET notion_page_id = ? WHERE id = ?;",
            (notion_page_id, article_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

# ==========================================
# SETTINGS OPERATIONS
# ==========================================

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?;", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default
    finally:
        conn.close()

def set_setting(key: str, value: str):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO settings (key, value, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP;
        """, (key, value))
        conn.commit()
    finally:
        conn.close()

def get_all_settings() -> Dict[str, str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings;")
        rows = cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        conn.close()

# ==========================================
# LIGHTWEIGHT SQL EXECUTION CONSOLE
# ==========================================

def execute_sql_query(query_str: str) -> Dict[str, Any]:
    """
    Executes an arbitrary SQL query against the internal SQLite database.
    Returns structured results for queries (SELECT/PRAGMA/EXPLAIN/WITH),
    or rowsAffected/mutation message for INSERT/UPDATE/DELETE/DDL.
    """
    clean = (query_str or "").strip()
    if not clean:
        return {
            "type": "error",
            "query": query_str,
            "error": "La instrucción SQL no puede estar vacía.",
            "executionTimeMs": 0.0
        }

    start = time.perf_counter()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        stmt = clean.rstrip(";").strip()
        first_word = stmt.split()[0].upper() if stmt.split() else ""

        if first_word in ("SELECT", "PRAGMA", "EXPLAIN", "WITH"):
            cursor.execute(clean)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchall()
            rows_as_dict = [dict(r) for r in raw_rows]
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "type": "query",
                "query": clean,
                "columns": columns,
                "rows": rows_as_dict,
                "rowCount": len(rows_as_dict),
                "executionTimeMs": duration_ms,
                "error": None
            }
        else:
            if ";" in stmt:
                cursor.executescript(clean)
                rows_affected = cursor.rowcount
            else:
                cursor.execute(clean)
                rows_affected = cursor.rowcount
            conn.commit()
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "type": "mutation",
                "query": clean,
                "rowsAffected": rows_affected,
                "message": f"Instrucción SQL ejecutada con éxito. Filas afectadas: {rows_affected}",
                "executionTimeMs": duration_ms,
                "error": None
            }
    except Exception as e:
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "type": "error",
            "query": clean,
            "error": str(e),
            "executionTimeMs": duration_ms
        }
    finally:
        conn.close()
