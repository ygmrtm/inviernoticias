import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import Parser from 'rss-parser';
import { GoogleGenAI } from '@google/genai';
import db from './db.js';
import { publishToNotion } from './notion.js';

dotenv.config();

const app = express();
const port = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

// Initialize Gemini API
const ai = new GoogleGenAI({
    apiKey: process.env.GEMINI_API_KEY
});

// 1. GET /api/feeds - List all RSS feeds
app.get('/api/feeds', async (req, res) => {
    try {
        const feeds = await db.getFeeds();
        res.json(feeds);
    } catch (error) {
        console.error('Error fetching feeds:', error);
        res.status(500).json({ error: 'Failed to retrieve feeds.' });
    }
});

// 2. POST /api/feeds - Add a new RSS feed
app.post('/api/feeds', async (req, res) => {
    try {
        const { url, name } = req.body;
        if (!url || !name) {
            return res.status(400).json({ error: 'URL and Name are required.' });
        }
        await db.addFeed(url, name);
        res.status(201).json({ message: 'Feed added successfully.' });
    } catch (error) {
        console.error('Error adding feed:', error);
        if (error.message.includes('UNIQUE')) {
            res.status(400).json({ error: 'Feed URL already exists.' });
        } else {
            res.status(500).json({ error: 'Failed to add feed.' });
        }
    }
});

// 3. DELETE /api/feeds/:id - Delete an RSS feed
app.delete('/api/feeds/:id', async (req, res) => {
    try {
        const { id } = req.params;
        await db.deleteFeed(id);
        res.json({ message: 'Feed deleted successfully.' });
    } catch (error) {
        console.error('Error deleting feed:', error);
        res.status(500).json({ error: 'Failed to delete feed.' });
    }
});

// 4. GET /api/articles - List synced articles with filtering
app.get('/api/articles', async (req, res) => {
    try {
        const limit = parseInt(req.query.limit) || 20;
        const offset = parseInt(req.query.offset) || 0;
        const feedId = req.query.feedId ? parseInt(req.query.feedId) : null;
        
        let hasAnalysis = null;
        if (req.query.hasAnalysis === 'true') hasAnalysis = true;
        if (req.query.hasAnalysis === 'false') hasAnalysis = false;

        const articles = await db.getArticles({ limit, offset, feedId, hasAnalysis });
        res.json(articles);
    } catch (error) {
        console.error('Error retrieving articles:', error);
        res.status(500).json({ error: 'Failed to retrieve articles.' });
    }
});

// 5. POST /api/feeds/sync - Sync articles from all or specific feed
app.post('/api/feeds/sync', async (req, res) => {
    try {
        const { feedId, limit = 50, dateRangeStart, dateRangeEnd } = req.body;

        let feeds = [];
        if (feedId) {
            const feed = await db.get('SELECT * FROM feeds WHERE id = ?', [feedId]);
            if (!feed) {
                return res.status(404).json({ error: 'Feed not found.' });
            }
            feeds = [feed];
        } else {
            feeds = await db.getFeeds();
        }

        const parser = new Parser();
        let totalSynced = 0;

        for (const feed of feeds) {
            console.log(`Syncing feed: ${feed.name} (${feed.url})`);
            try {
                const parsedFeed = await parser.parseURL(feed.url);
                const items = parsedFeed.items || [];
                
                let count = 0;
                for (const item of items) {
                    if (count >= limit) break;

                    const pubDateString = item.pubDate || item.isoDate;
                    const pubDate = pubDateString ? new Date(pubDateString) : new Date();

                    // Filter by date range if provided
                    if (dateRangeStart && pubDate < new Date(dateRangeStart)) continue;
                    if (dateRangeEnd && pubDate > new Date(dateRangeEnd)) continue;

                    const article = {
                        feedId: feed.id,
                        guid: item.guid || item.link || `${feed.id}-${Date.now()}-${count}`,
                        title: item.title || 'Sin Título',
                        link: item.link || '',
                        pubDate: pubDate.toISOString(),
                        content: item.contentSnippet || item.content || item.summary || ''
                    };

                    const result = await db.addArticle(article);
                    if (result && result.changes > 0) {
                        totalSynced++;
                    }
                    count++;
                }
            } catch (feedError) {
                console.error(`Error syncing feed ${feed.name}:`, feedError);
            }
        }

        res.json({ message: `Sincronización completada. ${totalSynced} artículos nuevos importados.`, syncedCount: totalSynced });
    } catch (error) {
        console.error('Error syncing feeds:', error);
        res.status(500).json({ error: 'Failed to sync feeds: ' + error.message });
    }
});

// 6. POST /api/articles/:id/analyze - Run Gemini Satire/Fact analysis
app.post('/api/articles/:id/analyze', async (req, res) => {
    try {
        const { id } = req.params;
        const article = await db.getArticleById(id);

        if (!article) {
            return res.status(404).json({ error: 'Article not found.' });
        }

        const prompt = `
You are an expert fact-checker, bias analyst, and cultural editor specializing in Mexican news, slang, and satire.
Analyze the following article title and description content. 

You must evaluate:
1. Whether it is satire/humorous/fictional (e.g., El Deforma style) which qualifies as "Mock-ticia" (isSatire: true), or if it is a real/actual news piece ("Real-ticia", isSatire: false).
2. The percentage of truth (truthScore: 0 to 100) and sarcasm (sarcasmScore: 0 to 100).
3. Whether the situation is surreal, absurd, or bizarre enough to qualify for the "México Mágico" badge (mexicoMagicoAward: true/false). This badge is called "Mexico Mágico se la deja ir a la IA".
4. A fitting Mexican proverb/saying ("refrán") related to the topic or situation.
5. A relevant quote from a prominent historical or important figure in Mexican history (e.g., Benito Juárez, Octavio Paz, Cantinflas, Sor Juana, Jose Vasconcelos, etc.) ONLY if it fits, otherwise null.
6. A breakdown explanation for a foreigner ("foreignerExplanation") so they can understand the joke, cultural context, or slang without needing to be Mexican.
7. Any specific reference to Mexican culture, society, slang, or current events.
8. Contrast sources: use search grounding to verify the facts and suggest related real-news articles to contrast or check.

Provide the output in valid JSON format with exactly the following structure:
{
  "isSatire": <true / false>,
  "truthScore": <number from 0 to 100>,
  "sarcasmScore": <number from 0 to 100>,
  "mexicoMagicoAward": <true / false>,
  "refran": "<Mexican refrán / saying>",
  "historicalQuote": "<Quote from historical figure or null>",
  "foreignerExplanation": "<Explanation for a foreigner>",
  "mexicanCultureReferences": "<Specific cultural references found>",
  "analysisSummary": "<A short, clear paragraph explaining your overall findings>",
  "relatedSources": [
    "<Source/article URL or Title 1>",
    "<Source/article URL or Title 2>"
  ]
}

Ensure the response is ONLY valid JSON in Spanish, do not include markdown code blocks like \`\`\`json or \`\`\`. 

Article Title:
"${article.title}"

Article Description/Content:
"${article.content}"
        `;

        let response;
        try {
            console.log(`Analyzing article "${article.title}" with Gemini Search Grounding...`);
            response = await ai.models.generateContent({
                model: 'gemini-2.5-flash',
                contents: prompt,
                config: {
                    tools: [{ googleSearch: {} }]
                }
            });
        } catch (searchError) {
            console.warn('Fallback to standard gemini generation without search grounding...', searchError);
            response = await ai.models.generateContent({
                model: 'gemini-2.5-flash',
                contents: prompt
            });
        }

        const resultText = response.text;
        
        try {
            // Clean up JSON block
            const cleanedText = resultText.replace(/^\s*\`\`\`json/m, '').replace(/\`\`\`\s*$/m, '').trim();
            const analysisResult = JSON.parse(cleanedText);
            
            await db.updateArticleAnalysis(id, analysisResult);
            res.json(analysisResult);
        } catch (parseError) {
            console.error('Error parsing JSON from Gemini:', parseError, 'Raw response:', resultText);
            res.status(500).json({ error: 'Failed to parse analysis results from AI.' });
        }

    } catch (error) {
        console.error('Error analyzing article:', error);
        res.status(500).json({ error: 'An error occurred during analysis.' });
    }
});

// 7. POST & GET /api/articles/:id/notion - Sync article results to Notion Database
app.route('/api/articles/:id/notion')
    .post(handleNotionSync)
    .get(handleNotionSync);

async function handleNotionSync(req, res) {
    try {
        const { id } = req.params;
        const article = await db.getArticleById(id);

        if (!article) {
            return res.status(404).json({ error: 'Article not found.' });
        }

        if (!article.analysis) {
            return res.status(400).json({ error: 'Article has not been analyzed yet. Run analysis first.' });
        }

        const analysis = JSON.parse(article.analysis);
        console.log(`Publishing article "${article.title}" to Notion...`);
        
        const notionPageId = await publishToNotion(article, analysis);
        await db.updateArticleNotionPage(id, notionPageId);

        res.json({ message: 'Articulo publicado en Notion con éxito.', notionPageId });
    } catch (error) {
        console.error('Error syncing to Notion:', error);
        res.status(500).json({ error: 'Failed to sync to Notion: ' + error.message });
    }
}

app.listen(port, () => {
    console.log(`Backend server running on port ${port}`);
});
