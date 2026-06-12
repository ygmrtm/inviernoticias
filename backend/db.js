import sqlite3 from 'sqlite3';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const dbPath = path.join(__dirname, 'inviernoticias.db');

// Initialize sqlite3 database
const db = new sqlite3.Database(dbPath, (err) => {
    if (err) {
        console.error('Error opening database:', err.message);
    } else {
        console.log('Connected to SQLite database at:', dbPath);
        initSchema();
    }
});

// Helper to run query and return Promise
const run = (sql, params = []) => {
    return new Promise((resolve, reject) => {
        db.run(sql, params, function (err) {
            if (err) reject(err);
            else resolve(this);
        });
    });
};

// Helper to get all rows
const all = (sql, params = []) => {
    return new Promise((resolve, reject) => {
        db.all(sql, params, (err, rows) => {
            if (err) reject(err);
            else resolve(rows);
        });
    });
};

// Helper to get single row
const get = (sql, params = []) => {
    return new Promise((resolve, reject) => {
        db.get(sql, params, (err, row) => {
            if (err) reject(err);
            else resolve(row);
        });
    });
};

// Initialize schema
async function initSchema() {
    try {
        await run(`
            CREATE TABLE IF NOT EXISTS feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        `);

        await run(`
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id INTEGER,
                guid TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                pub_date DATETIME,
                content TEXT,
                analysis TEXT, -- JSON string of Gemini analysis
                notion_page_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(feed_id) REFERENCES feeds(id) ON DELETE CASCADE
            )
        `);

        // Insert a default feed for El Deforma if not exists
        const deformaUrl = 'https://eldeforma.com/feed/';
        const existingFeed = await get('SELECT id FROM feeds WHERE url = ?', [deformaUrl]);
        if (!existingFeed) {
            await run('INSERT INTO feeds (url, name) VALUES (?, ?)', [deformaUrl, 'El Deforma']);
            console.log('Inserted default El Deforma feed');
        }

        console.log('SQLite database schema initialized successfully');
    } catch (err) {
        console.error('Error initializing SQLite schema:', err);
    }
}

export default {
    run,
    all,
    get,
    
    // Feeds operations
    async getFeeds() {
        return all('SELECT * FROM feeds ORDER BY created_at DESC');
    },

    async addFeed(url, name) {
        return run('INSERT INTO feeds (url, name) VALUES (?, ?)', [url, name]);
    },

    async deleteFeed(id) {
        return run('DELETE FROM feeds WHERE id = ?', [id]);
    },

    // Articles operations
    async addArticle({ feedId, guid, title, link, pubDate, content }) {
        return run(
            `INSERT OR IGNORE INTO articles (feed_id, guid, title, link, pub_date, content) 
             VALUES (?, ?, ?, ?, ?, ?)`,
            [feedId, guid, title, link, pubDate, content]
        );
    },

    async getArticles({ limit = 20, offset = 0, feedId = null, hasAnalysis = null } = {}) {
        let sql = 'SELECT * FROM articles';
        const params = [];
        const conditions = [];

        if (feedId !== null) {
            conditions.push('feed_id = ?');
            params.push(feedId);
        }

        if (hasAnalysis !== null) {
            if (hasAnalysis) {
                conditions.push('analysis IS NOT NULL');
            } else {
                conditions.push('analysis IS NULL');
            }
        }

        if (conditions.length > 0) {
            sql += ' WHERE ' + conditions.join(' AND ');
        }

        sql += ' ORDER BY pub_date DESC, id DESC LIMIT ? OFFSET ?';
        params.push(limit, offset);

        return all(sql, params);
    },

    async getArticleById(id) {
        return get('SELECT * FROM articles WHERE id = ?', [id]);
    },

    async updateArticleAnalysis(id, analysisJson) {
        return run('UPDATE articles SET analysis = ? WHERE id = ?', [JSON.stringify(analysisJson), id]);
    },

    async updateArticleNotionPage(id, pageId) {
        return run('UPDATE articles SET notion_page_id = ? WHERE id = ?', [pageId, id]);
    }
};
