import { Client } from '@notionhq/client';
import dotenv from 'dotenv';

dotenv.config();

let notion = null;
if (process.env.NOTION_TOKEN) {
    notion = new Client({ auth: process.env.NOTION_TOKEN });
}

export async function publishToNotion(article, analysis) {
    if (!notion || !process.env.NOTION_DATABASE_ID) {
        console.warn('Notion is not configured. Missing NOTION_TOKEN or NOTION_DATABASE_ID in env.');
        throw new Error('Notion configuration is missing. Please set NOTION_TOKEN and NOTION_DATABASE_ID in your .env file.');
    }

    const { title, link, pub_date } = article;
    const { 
        isSatire = false,
        truthScore = 0, 
        sarcasmScore = 0, 
        mexicoMagicoAward = false, 
        refran = 'N/A', 
        analysisSummary = '',
        foreignerExplanation = '',
        mexicanCultureReferences = '',
        historicalQuote = '',
        relatedSources = []
    } = analysis;

    try {
        const response = await notion.pages.create({
            parent: { database_id: process.env.NOTION_DATABASE_ID },
            properties: {
                Name: {
                    title: [
                        {
                            text: {
                                content: title || 'Noticia sin título'
                            }
                        }
                    ]
                },
                URL: {
                    url: link || 'http://localhost'
                },
                Type: {
                    select: {
                        name: isSatire ? 'Mock-ticia' : 'Real-ticia'
                    }
                },
                'Truth %': {
                    number: Number(truthScore)/100 || 0
                },
                'Sarcasm %': {
                    number: Number(sarcasmScore)/100 || 0
                },
                'México Mágico': {
                    checkbox: !!mexicoMagicoAward
                },
                'Refrán': {
                    rich_text: [
                        {
                            text: {
                                content: refran || 'N/A'
                            }
                        }
                    ]
                },
                'Published Date': {
                    date: pub_date ? { start: new Date(pub_date).toISOString() } : null
                }
            },
            children: [
                {
                    object: 'block',
                    type: 'heading_2',
                    heading_2: {
                        rich_text: [{ type: 'text', text: { content: 'Resumen del Análisis' } }]
                    }
                },
                {
                    object: 'block',
                    type: 'paragraph',
                    paragraph: {
                        rich_text: [{ type: 'text', text: { content: analysisSummary || 'Sin resumen disponible.' } }]
                    }
                },
                {
                    object: 'block',
                    type: 'heading_2',
                    heading_2: {
                        rich_text: [{ type: 'text', text: { content: 'Explicación para Extranjeros' } }]
                    }
                },
                {
                    object: 'block',
                    type: 'paragraph',
                    paragraph: {
                        rich_text: [{ type: 'text', text: { content: foreignerExplanation || 'N/A' } }]
                    }
                },
                {
                    object: 'block',
                    type: 'heading_2',
                    heading_2: {
                        rich_text: [{ type: 'text', text: { content: 'Referencias Culturales y Citas Históricas' } }]
                    }
                },
                {
                    object: 'block',
                    type: 'paragraph',
                    paragraph: {
                        rich_text: [
                            { 
                                type: 'text', 
                                text: { 
                                    content: `Referencias: ${mexicanCultureReferences || 'Ninguna'}\n\nCita Histórica: ${historicalQuote || 'Ninguna'}` 
                                } 
                            }
                        ]
                    }
                },
                {
                    object: 'block',
                    type: 'heading_2',
                    heading_2: {
                        rich_text: [{ type: 'text', text: { content: 'Fuentes y Búsqueda Relacionada' } }]
                    }
                },
                {
                    object: 'block',
                    type: 'paragraph',
                    paragraph: {
                        rich_text: [
                            { 
                                type: 'text', 
                                text: { 
                                    content: Array.isArray(relatedSources) ? relatedSources.join('\n') : (relatedSources || 'N/A') 
                                } 
                            }
                        ]
                    }
                }
            ]
        });

        return response.id;
    } catch (error) {
        console.error('Error publishing page to Notion:', error);
        throw error;
    }
}
