import { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  ShieldAlert, 
  Activity, 
  CheckCircle, 
  AlertTriangle, 
  Rss, 
  Trash2, 
  Calendar, 
  FileText, 
  Send, 
  HelpCircle, 
  BookOpen, 
  Quote, 
  Info, 
  Search, 
  RefreshCw, 
  ExternalLink,
  ChevronRight,
  Plus
} from 'lucide-react';
import './index.css';

const API_BASE = 'http://localhost:3001/api';

function App() {
  const [activeTab, setActiveTab] = useState('rss');
  
  // RSS States
  const [feeds, setFeeds] = useState([]);
  const [articles, setArticles] = useState([]);
  const [activeFeedId, setActiveFeedId] = useState('');
  const [filterAnalysis, setFilterAnalysis] = useState('all'); // all, analyzed, pending
  
  // Feed Add Form
  const [newFeedUrl, setNewFeedUrl] = useState('');
  const [newFeedName, setNewFeedName] = useState('');
  
  // Sync Controls
  const [syncLimit, setSyncLimit] = useState(20);
  const [dateStart, setDateStart] = useState('');
  const [dateEnd, setDateEnd] = useState('');
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState('');
  
  // Detail View Modal & Action Loadings
  const [selectedArticle, setSelectedArticle] = useState(null);
  const [analyzingId, setAnalyzingId] = useState(null);
  const [notionSyncingId, setNotionSyncingId] = useState(null);
  const [error, setError] = useState('');

  // Direct Text Analysis States
  const [directText, setDirectText] = useState('');
  const [directLoading, setDirectLoading] = useState(false);
  const [directResult, setDirectResult] = useState(null);

  useEffect(() => {
    fetchFeeds();
    fetchArticles();
  }, [activeFeedId, filterAnalysis]);

  const fetchFeeds = async () => {
    try {
      const res = await axios.get(`${API_BASE}/feeds`);
      setFeeds(res.data);
    } catch (err) {
      console.error('Error fetching feeds:', err);
    }
  };

  const fetchArticles = async () => {
    try {
      const params = {};
      if (activeFeedId) params.feedId = activeFeedId;
      if (filterAnalysis === 'analyzed') params.hasAnalysis = 'true';
      if (filterAnalysis === 'pending') params.hasAnalysis = 'false';
      
      const res = await axios.get(`${API_BASE}/articles`, { params });
      setArticles(res.data);
    } catch (err) {
      console.error('Error fetching articles:', err);
    }
  };

  const handleAddFeed = async (e) => {
    e.preventDefault();
    if (!newFeedUrl || !newFeedName) return;
    setError('');
    try {
      await axios.post(`${API_BASE}/feeds`, { url: newFeedUrl, name: newFeedName });
      setNewFeedUrl('');
      setNewFeedName('');
      fetchFeeds();
    } catch (err) {
      setError(err.response?.data?.error || 'Error al agregar feed RSS.');
    }
  };

  const handleDeleteFeed = async (id) => {
    if (!window.confirm('¿Estás seguro de que quieres eliminar este feed RSS y todos sus artículos?')) return;
    try {
      await axios.delete(`${API_BASE}/feeds/${id}`);
      if (activeFeedId === String(id)) setActiveFeedId('');
      fetchFeeds();
      fetchArticles();
    } catch (err) {
      console.error('Error deleting feed:', err);
    }
  };

  const handleSyncFeeds = async () => {
    setSyncing(true);
    setSyncResult('');
    setError('');
    try {
      const payload = {
        limit: syncLimit,
      };
      if (activeFeedId) payload.feedId = activeFeedId;
      if (dateStart) payload.dateRangeStart = dateStart;
      if (dateEnd) payload.dateRangeEnd = dateEnd;

      const res = await axios.post(`${API_BASE}/feeds/sync`, payload);
      setSyncResult(res.data.message);
      fetchArticles();
    } catch (err) {
      setError('Error al sincronizar feeds: ' + (err.response?.data?.error || err.message));
    } finally {
      setSyncing(false);
    }
  };

  const handleAnalyzeArticle = async (id, e) => {
    if (e) e.stopPropagation();
    setAnalyzingId(id);
    setError('');
    try {
      const res = await axios.post(`${API_BASE}/articles/${id}/analyze`);
      
      // Update selectedArticle details if it's currently open
      if (selectedArticle && selectedArticle.id === id) {
        setSelectedArticle({ ...selectedArticle, analysis: JSON.stringify(res.data) });
      }
      
      // Refresh articles list
      fetchArticles();
    } catch (err) {
      setError('Error en el análisis de Gemini: ' + (err.response?.data?.error || err.message));
    } finally {
      setAnalyzingId(null);
    }
  };

  const handleSyncToNotion = async (id, e) => {
    if (e) e.stopPropagation();
    setNotionSyncingId(id);
    setError('');
    try {
      const res = await axios.post(`${API_BASE}/articles/${id}/notion`);
      alert('¡Sincronizado a Notion con éxito!');
      
      // Update local article instance sync state
      if (selectedArticle && selectedArticle.id === id) {
        setSelectedArticle({ ...selectedArticle, notion_page_id: res.data.notionPageId });
      }
      fetchArticles();
    } catch (err) {
      setError('Error de Notion: ' + (err.response?.data?.error || err.message));
    } finally {
      setNotionSyncingId(null);
    }
  };

  const handleAnalyzeDirectText = async () => {
    if (!directText.trim()) return;
    setDirectLoading(true);
    setDirectResult(null);
    setError('');
    try {
      // Direct analyze uses the analyze api with custom content
      const response = await axios.post(`${API_BASE}/analyze`, { text: directText });
      setDirectResult(response.data);
    } catch (err) {
      setError('Error de análisis directo: ' + (err.response?.data?.error || err.message));
    } finally {
      setDirectLoading(false);
    }
  };

  const getScoreColorClass = (score) => {
    if (score >= 70) return '--success';
    if (score >= 40) return '--warning';
    return '--danger';
  };

  const formatPublishDate = (dateStr) => {
    if (!dateStr) return 'Fecha desconocida';
    const date = new Date(dateStr);
    return date.toLocaleDateString('es-MX', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Helper to safely parse analysis JSON
  const getAnalysisObj = (article) => {
    if (!article || !article.analysis) return null;
    try {
      return JSON.parse(article.analysis);
    } catch (e) {
      console.error('Error parsing article analysis', e);
      return null;
    }
  };

  return (
    <div>
      <header>
        <h1>Inviernoticias</h1>
        <p className="subtitle">Lector RSS Inteligente para Sátira y Noticias Reales con IA</p>
      </header>

      {/* Main navigation tabs */}
      <div style={{ display: 'flex', gap: '10px', marginBottom: '1.5rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '10px' }}>
        <button 
          onClick={() => setActiveTab('rss')} 
          className={`btn ${activeTab === 'rss' ? 'btn-primary' : 'btn-secondary'}`}
        >
          <Rss size={18} /> Lector RSS
        </button>
        <button 
          onClick={() => setActiveTab('direct')} 
          className={`btn ${activeTab === 'direct' ? 'btn-primary' : 'btn-secondary'}`}
        >
          <FileText size={18} /> Análisis Directo
        </button>
      </div>

      {error && (
        <div className="error-message" role="alert" style={{ marginBottom: '1.5rem' }}>
          <AlertTriangle size={20} style={{ verticalAlign: 'middle', marginRight: '8px' }} />
          {error}
        </div>
      )}

      {activeTab === 'rss' ? (
        <div className="dashboard-grid">
          
          {/* Sidebar Panel */}
          <aside style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            
            {/* Feeds Manager Card */}
            <div className="card">
              <div className="card-title">
                <Rss size={20} color="var(--accent)" /> Feeds RSS
              </div>
              <form onSubmit={handleAddFeed} style={{ marginBottom: '1rem' }}>
                <div className="form-group">
                  <label htmlFor="feed-name">Nombre del Sitio</label>
                  <input 
                    id="feed-name"
                    type="text" 
                    value={newFeedName} 
                    onChange={e => setNewFeedName(e.target.value)} 
                    placeholder="Ej. El Deforma"
                    required
                  />
                </div>
                <div className="form-group">
                  <label htmlFor="feed-url">URL RSS</label>
                  <input 
                    id="feed-url"
                    type="url" 
                    value={newFeedUrl} 
                    onChange={e => setNewFeedUrl(e.target.value)} 
                    placeholder="https://eldeforma.com/feed/"
                    required
                  />
                </div>
                <button type="submit" className="btn btn-accent btn-full">
                  <Plus size={16} /> Agregar Feed
                </button>
              </form>

              {/* Feed items list */}
              <div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px', fontWeight: 'bold' }}>SITIOS ACTIVOS:</div>
                <div 
                  className={`feed-item ${activeFeedId === '' ? 'active' : ''}`}
                  onClick={() => setActiveFeedId('')}
                  style={{ cursor: 'pointer', backgroundColor: activeFeedId === '' ? 'rgba(59, 130, 246, 0.15)' : '', borderColor: activeFeedId === '' ? 'var(--primary)' : '' }}
                >
                  <span>Todos los artículos</span>
                </div>
                {feeds.map(f => (
                  <div 
                    key={f.id} 
                    className="feed-item"
                    onClick={() => setActiveFeedId(String(f.id))}
                    style={{ 
                      cursor: 'pointer', 
                      backgroundColor: activeFeedId === String(f.id) ? 'rgba(59, 130, 246, 0.15)' : '', 
                      borderColor: activeFeedId === String(f.id) ? 'var(--primary)' : '' 
                    }}
                  >
                    <span>{f.name}</span>
                    <button 
                      onClick={(e) => { e.stopPropagation(); handleDeleteFeed(f.id); }} 
                      style={{ background: 'transparent', padding: '2px', border: 'none', cursor: 'pointer', color: 'var(--danger)' }}
                      title="Eliminar feed"
                      aria-label={`Eliminar feed ${f.name}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {/* Sync Feeds Control Card */}
            <div className="card">
              <div className="card-title">
                <RefreshCw size={20} color="var(--primary)" /> Sincronizar RSS
              </div>
              <div className="form-group">
                <label htmlFor="sync-limit">Límite de Artículos</label>
                <select id="sync-limit" value={syncLimit} onChange={e => setSyncLimit(Number(e.target.value))}>
                  <option value={10}>10 artículos</option>
                  <option value={20}>20 artículos</option>
                  <option value={50}>50 artículos</option>
                  <option value={100}>100 artículos</option>
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="date-start">Fecha Inicio</label>
                <input id="date-start" type="date" value={dateStart} onChange={e => setDateStart(e.target.value)} />
              </div>
              <div className="form-group">
                <label htmlFor="date-end">Fecha Fin</label>
                <input id="date-end" type="date" value={dateEnd} onChange={e => setDateEnd(e.target.value)} />
              </div>
              <button 
                onClick={handleSyncFeeds} 
                disabled={syncing}
                className="btn btn-primary btn-full"
              >
                {syncing ? (
                  <>
                    <Activity className="spinner" size={16} />
                    Sincronizando...
                  </>
                ) : (
                  <>
                    <RefreshCw size={16} />
                    Sincronizar Ahora
                  </>
                )}
              </button>
              {syncResult && (
                <div style={{ marginTop: '10px', fontSize: '0.85rem', color: 'var(--success)', textAlign: 'center', fontWeight: 'bold' }}>
                  {syncResult}
                </div>
              )}
            </div>

          </aside>

          {/* Main Articles List Area */}
          <main>
            <div className="articles-header">
              <h2>Artículos Sincronizados</h2>
              <div style={{ display: 'flex', gap: '8px' }}>
                <select 
                  aria-label="Filtrar por estado de análisis"
                  value={filterAnalysis} 
                  onChange={e => setFilterAnalysis(e.target.value)}
                  style={{ padding: '6px 12px', fontSize: '0.85rem' }}
                >
                  <option value="all">Ver Todos</option>
                  <option value="analyzed">Solo Analizados</option>
                  <option value="pending">Pendientes de Análisis</option>
                </select>
              </div>
            </div>

            {articles.length === 0 ? (
              <div className="empty-state card">
                <FileText size={48} style={{ marginBottom: '1rem', opacity: 0.5 }} />
                <p>No se encontraron artículos.</p>
                <p style={{ fontSize: '0.85rem', marginTop: '5px' }}>Presiona "Sincronizar Ahora" en la barra lateral para importar.</p>
              </div>
            ) : (
              <div className="articles-list">
                {articles.map(article => {
                  const analysis = getAnalysisObj(article);
                  
                  return (
                    <div 
                      key={article.id} 
                      className="article-card"
                      onClick={() => setSelectedArticle(article)}
                    >
                      <div className="article-meta">
                        <span>{formatPublishDate(article.pub_date)}</span>
                        {analysis && (
                          <>
                            <span className={`badge ${analysis.isSatire ? 'badge-satire' : 'badge-real'}`}>
                              {analysis.isSatire ? 'Mock-ticia' : 'Real-ticia'}
                            </span>
                            {analysis.mexicoMagicoAward && (
                              <span className="badge badge-mexico">México Mágico 🇲🇽</span>
                            )}
                          </>
                        )}
                        {article.notion_page_id && (
                          <span className="badge badge-notion">Notion Sync</span>
                        )}
                      </div>
                      
                      <div className="article-title">{article.title}</div>
                      <div className="article-desc">{article.content}</div>

                      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '10px' }}>
                        {!analysis ? (
                          <button 
                            className="btn btn-secondary btn-full"
                            style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                            onClick={(e) => handleAnalyzeArticle(article.id, e)}
                            disabled={analyzingId === article.id}
                          >
                            {analyzingId === article.id ? (
                              <Activity className="spinner" size={14} />
                            ) : 'Analizar Noticia'}
                          </button>
                        ) : (
                          <>
                            <div style={{ marginRight: 'auto', display: 'flex', gap: '15px', alignItems: 'center', fontSize: '0.85rem' }}>
                              <span>Veracidad: <strong style={{ color: `var(${getScoreColorClass(analysis.truthScore)})` }}>{analysis.truthScore}%</strong></span>
                              <span>Sarcasmo: <strong>{analysis.sarcasmScore}%</strong></span>
                            </div>
                            
                            {!article.notion_page_id && (
                              <button 
                                className="btn btn-secondary"
                                style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                                onClick={(e) => handleSyncToNotion(article.id, e)}
                                disabled={notionSyncingId === article.id}
                              >
                                {notionSyncingId === article.id ? (
                                  <Activity className="spinner" size={14} />
                                ) : 'Sincronizar a Notion'}
                              </button>
                            )}
                          </>
                        )}
                        <span style={{ display: 'flex', alignItems: 'center', color: 'var(--text-muted)' }}>
                          <ChevronRight size={18} />
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </main>
        </div>
      ) : (
        
        /* Direct Text analysis view */
        <main className="card" style={{ maxWidth: '800px', margin: '0 auto' }}>
          <h2 style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileText color="var(--accent)" /> Análisis Libre de Noticia
          </h2>
          <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem', fontSize: '0.95rem' }}>
            Pega el texto de cualquier noticia, anuncio o publicación en redes sociales para que Gemini analice si es sátira, su nivel de sarcasmo, veracidad e interprete sus referencias de cultura popular mexicana.
          </p>

          <div className="form-group" style={{ marginBottom: '1.5rem' }}>
            <label htmlFor="direct-textarea">Texto completo a analizar</label>
            <textarea 
              id="direct-textarea"
              value={directText} 
              onChange={e => setDirectText(e.target.value)} 
              placeholder="Ej. Gobierno declara que quesadillas sin queso serán catalogadas oficialmente como tacos..."
              style={{ height: '180px' }}
            />
          </div>

          <button 
            onClick={handleAnalyzeDirectText} 
            disabled={directLoading || !directText.trim()}
            className="btn btn-primary btn-full"
            style={{ marginBottom: '2rem' }}
          >
            {directLoading ? (
              <>
                <Activity className="spinner" size={18} />
                Analizando con Gemini (Grounding activo)...
              </>
            ) : (
              <>
                <Send size={18} />
                Iniciar Análisis Completo
              </>
            )}
          </button>

          {directResult && (
            <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '2rem' }}>
              <h3 style={{ marginBottom: '1.5rem', textAlign: 'center' }}>Resultados del Análisis Directo</h3>

              <div style={{ display: 'flex', justifyContent: 'center', gap: '15px', marginBottom: '2rem', flexWrap: 'wrap' }}>
                <span className={`badge ${directResult.isSatire ? 'badge-satire' : 'badge-real'}`} style={{ fontSize: '1rem', padding: '8px 16px' }}>
                  {directResult.isSatire ? 'Mock-ticia (Sátira)' : 'Real-ticia (Noticia Real)'}
                </span>
                {directResult.mexicoMagicoAward && (
                  <span className="badge badge-mexico" style={{ fontSize: '1rem', padding: '8px 16px' }}>
                    México Mágico 🇲🇽
                  </span>
                )}
              </div>

              <div className="analysis-scores-grid">
                <div className="score-meter-card">
                  <div className="score-meter-value" style={{ color: `var(${getScoreColorClass(directResult.truthScore)})` }}>
                    {directResult.truthScore}%
                  </div>
                  <div className="meter-bar-container">
                    <div 
                      className="meter-bar-fill" 
                      style={{ 
                        width: `${directResult.truthScore}%`, 
                        backgroundColor: `var(${getScoreColorClass(directResult.truthScore)})` 
                      }}
                    />
                  </div>
                  <div className="score-meter-label">Veracidad / Verdad</div>
                </div>

                <div className="score-meter-card">
                  <div className="score-meter-value" style={{ color: 'var(--purple)' }}>
                    {directResult.sarcasmScore}%
                  </div>
                  <div className="meter-bar-container">
                    <div 
                      className="meter-bar-fill" 
                      style={{ 
                        width: `${directResult.sarcasmScore}%`, 
                        backgroundColor: 'var(--purple)' 
                      }}
                    />
                  </div>
                  <div className="score-meter-label">Sarcasmo / Ironía</div>
                </div>
              </div>

              {/* Analysis Text sections */}
              <div className="analysis-section-card">
                <div className="analysis-section-title"><Activity size={16} /> Resumen del Fact-Checking</div>
                <div className="analysis-section-content">{directResult.analysisSummary}</div>
              </div>

              <div className="analysis-section-card">
                <div className="analysis-section-title"><HelpCircle size={16} /> Explicación para Extranjeros</div>
                <div className="analysis-section-content">{directResult.foreignerExplanation}</div>
              </div>

              <div className="analysis-section-card">
                <div className="analysis-section-title"><BookOpen size={16} /> Referencias Culturales Mexicanas</div>
                <div className="analysis-section-content">{directResult.mexicanCultureReferences}</div>
              </div>

              {directResult.refran && directResult.refran !== 'No aplica' && (
                <div className="analysis-section-card">
                  <div className="analysis-section-title"><Info size={16} /> Refrán Mexicano Relacionado</div>
                  <div className="analysis-section-content proverb-box">
                    "{directResult.refran}"
                  </div>
                </div>
              )}

              {directResult.historicalQuote && (
                <div className="analysis-section-card">
                  <div className="analysis-section-title"><Quote size={16} /> Cita de Personaje Histórico</div>
                  <div className="analysis-section-content quote-box">
                    "{directResult.historicalQuote}"
                  </div>
                </div>
              )}

              {directResult.relatedSources && directResult.relatedSources.length > 0 && (
                <div className="analysis-section-card">
                  <div className="analysis-section-title"><Search size={16} /> Fuentes de Contraste Consultadas</div>
                  <div className="analysis-section-content">
                    <ul style={{ listStyleType: 'disc', paddingLeft: '20px' }}>
                      {directResult.relatedSources.map((src, i) => (
                        <li key={i} style={{ marginBottom: '5px' }}>{src}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      )}

      {/* Detailed view Modal */}
      {selectedArticle && (() => {
        const analysis = getAnalysisObj(selectedArticle);
        
        return (
          <div className="modal-overlay" onClick={() => setSelectedArticle(null)}>
            <div className="modal-content" onClick={e => e.stopPropagation()}>
              <button className="close-btn" onClick={() => setSelectedArticle(null)} aria-label="Cerrar modal">×</button>
              
              <div className="analysis-header">
                <div className="article-meta" style={{ marginBottom: '8px' }}>
                  <span>{formatPublishDate(selectedArticle.pub_date)}</span>
                  {selectedArticle.link && (
                    <a href={selectedArticle.link} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', color: 'var(--primary)' }}>
                      Leer original <ExternalLink size={12} />
                    </a>
                  )}
                </div>
                <h2>{selectedArticle.title}</h2>
              </div>

              {!analysis ? (
                <div style={{ textAlign: 'center', padding: '3rem' }}>
                  <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem' }}>Este artículo aún no ha sido analizado por Gemini.</p>
                  <button 
                    onClick={() => handleAnalyzeArticle(selectedArticle.id)}
                    disabled={analyzingId === selectedArticle.id}
                    className="btn btn-primary"
                  >
                    {analyzingId === selectedArticle.id ? (
                      <>
                        <Activity className="spinner" size={16} />
                        Fact-Checking con Gemini...
                      </>
                    ) : 'Realizar Análisis Completo'}
                  </button>
                </div>
              ) : (
                <div>
                  <div style={{ display: 'flex', gap: '15px', marginBottom: '2rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                    <span className={`badge ${analysis.isSatire ? 'badge-satire' : 'badge-real'}`} style={{ fontSize: '0.9rem', padding: '6px 14px' }}>
                      {analysis.isSatire ? 'Mock-ticia' : 'Real-ticia'}
                    </span>
                    {analysis.mexicoMagicoAward && (
                      <span className="badge badge-mexico" style={{ fontSize: '0.9rem', padding: '6px 14px' }}>
                        ¡Galardón México Mágico! 🇲🇽
                      </span>
                    )}
                    {selectedArticle.notion_page_id && (
                      <span className="badge badge-notion" style={{ fontSize: '0.9rem', padding: '6px 14px' }}>
                        Sincronizado en Notion
                      </span>
                    )}
                  </div>

                  <div className="analysis-scores-grid">
                    <div className="score-meter-card">
                      <div className="score-meter-value" style={{ color: `var(${getScoreColorClass(analysis.truthScore)})` }}>
                        {analysis.truthScore}%
                      </div>
                      <div className="meter-bar-container">
                        <div 
                          className="meter-bar-fill" 
                          style={{ 
                            width: `${analysis.truthScore}%`, 
                            backgroundColor: `var(${getScoreColorClass(analysis.truthScore)})` 
                          }}
                        />
                      </div>
                      <div className="score-meter-label">Veracidad / Verdad</div>
                    </div>

                    <div className="score-meter-card">
                      <div className="score-meter-value" style={{ color: 'var(--purple)' }}>
                        {analysis.sarcasmScore}%
                      </div>
                      <div className="meter-bar-container">
                        <div 
                          className="meter-bar-fill" 
                          style={{ 
                            width: `${analysis.sarcasmScore}%`, 
                            backgroundColor: 'var(--purple)' 
                          }}
                        />
                      </div>
                      <div className="score-meter-label">Sarcasmo / Ironía</div>
                    </div>
                  </div>

                  {/* detailed content sections */}
                  <div className="analysis-section-card">
                    <div className="analysis-section-title"><Activity size={16} /> Resumen del Fact-Checking</div>
                    <div className="analysis-section-content">{analysis.analysisSummary}</div>
                  </div>

                  <div className="analysis-section-card">
                    <div className="analysis-section-title"><HelpCircle size={16} /> Explicación para Extranjeros</div>
                    <div className="analysis-section-content">{analysis.foreignerExplanation}</div>
                  </div>

                  <div className="analysis-section-card">
                    <div className="analysis-section-title"><BookOpen size={16} /> Referencias Culturales Mexicanas</div>
                    <div className="analysis-section-content">{analysis.mexicanCultureReferences}</div>
                  </div>

                  {analysis.refran && analysis.refran !== 'No aplica' && (
                    <div className="analysis-section-card">
                      <div className="analysis-section-title"><Info size={16} /> Refrán Mexicano Relacionado</div>
                      <div className="analysis-section-content proverb-box">
                        "{analysis.refran}"
                      </div>
                    </div>
                  )}

                  {analysis.historicalQuote && (
                    <div className="analysis-section-card">
                      <div className="analysis-section-title"><Quote size={16} /> Cita de Personaje Histórico</div>
                      <div className="analysis-section-content quote-box">
                        "{analysis.historicalQuote}"
                      </div>
                    </div>
                  )}

                  {analysis.relatedSources && analysis.relatedSources.length > 0 && (
                    <div className="analysis-section-card">
                      <div className="analysis-section-title"><Search size={16} /> Fuentes de Contraste Consultadas</div>
                      <div className="analysis-section-content">
                        <ul style={{ listStyleType: 'disc', paddingLeft: '20px' }}>
                          {analysis.relatedSources.map((src, i) => (
                            <li key={i} style={{ marginBottom: '5px' }}>{src}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '10px', marginTop: '2rem', justifyContent: 'flex-end' }}>
                    {!selectedArticle.notion_page_id ? (
                      <button 
                        onClick={() => handleSyncToNotion(selectedArticle.id)}
                        disabled={notionSyncingId === selectedArticle.id}
                        className="btn btn-accent"
                      >
                        {notionSyncingId === selectedArticle.id ? (
                          <>
                            <Activity className="spinner" size={16} />
                            Enviando a Notion...
                          </>
                        ) : 'Publicar reporte en Notion'}
                      </button>
                    ) : (
                      <div style={{ color: 'var(--success)', fontWeight: 'bold', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <CheckCircle size={18} /> Publicado en Notion
                      </div>
                    )}
                    <button className="btn btn-secondary" onClick={() => setSelectedArticle(null)}>
                      Cerrar
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
}

export default App;
