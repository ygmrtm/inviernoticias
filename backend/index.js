import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import { GoogleGenAI } from '@google/genai';

dotenv.config();

const app = express();
const port = process.env.PORT || 3001;

app.use(cors());
app.use(express.json());

// Initialize Gemini API
const ai = new GoogleGenAI({
    apiKey: process.env.GEMINI_API_KEY
});

app.post('/api/analyze', async (req, res) => {
    try {
        const { text } = req.body;

        if (!text) {
            return res.status(400).json({ error: 'News text is required' });
        }

        const prompt = `
You are an expert fact-checker and bias analyst. Analyze the following news text or advertisement. 
Identify any "red flags" (signs of fake news, sensationalism, lack of sources, logical fallacies) and determine the bias.
Provide the output in valid JSON format with exactly the following structure:
{
  "trustScore": <number from 0 to 100 representing the overall trustworthiness>,
  "bias": "<Short description of the bias, e.g., 'Right-leaning', 'Sensationalist', 'Neutral'>",
  "redFlags": [
    "<red flag 1>",
    "<red flag 2>"
  ],
  "analysisSummary": "<A short, clear paragraph explaining the findings>"
}

Ensure the response is ONLY valid JSON, do not include markdown code blocks like \`\`\`json or \`\`\`. 

Text to analyze:
"${text}"
        `;

        const response = await ai.models.generateContent({
            model: 'gemini-2.5-flash',
            contents: prompt,
        });

        const resultText = response.text;
        
        try {
            // Clean up the text in case Gemini wraps it in markdown blocks
            const cleanedText = resultText.replace(/^\\s*\\`\\`\\`json/m, '').replace(/\\`\\`\\`\\s*$/m, '').trim();
            const analysisResult = JSON.parse(cleanedText);
            res.json(analysisResult);
        } catch (parseError) {
            console.error('Error parsing JSON from Gemini:', parseError, 'Raw response:', resultText);
            res.status(500).json({ error: 'Failed to parse analysis results.' });
        }

    } catch (error) {
        console.error('Error analyzing text:', error);
        res.status(500).json({ error: 'An error occurred during analysis.' });
    }
});

app.listen(port, () => {
    console.log(`Backend server running on port ${port}`);
});
