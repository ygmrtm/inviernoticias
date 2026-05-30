import { useState } from 'react';
import axios from 'axios';
import { ShieldAlert, Activity, CheckCircle, AlertTriangle } from 'lucide-react';
import './index.css';

function App() {
  const [text, setText] = useState('');
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [error, setError] = useState('');

  const handleAnalyze = async () => {
    if (!text.trim()) {
      setError('Por favor, ingresa el texto de la noticia o aviso antes de analizar.');
      return;
    }

    setLoading(true);
    setError('');
    setResults(null);

    try {
      const response = await axios.post('http://localhost:3001/api/analyze', { text });
      setResults(response.data);
    } catch (err) {
      console.error(err);
      setError('Hubo un error al analizar el texto. Por favor, asegúrate de que el servidor esté funcionando y que tengas la clave de API correcta.');
    } finally {
      setLoading(false);
    }
  };

  const getScoreClass = (score) => {
    if (score >= 70) return 'score-high';
    if (score >= 40) return 'score-medium';
    return 'score-low';
  };

  return (
    <div>
      <header>
        <h1>Detector de Noticias Falsas y Sesgo</h1>
        <p className="subtitle">Pega el texto de una noticia para analizar si es confiable o si tiene banderas rojas.</p>
      </header>

      <main>
        <section className="input-section">
          <label htmlFor="news-text">Texto de la noticia o aviso:</label>
          <textarea
            id="news-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Pega el texto aquí..."
            aria-label="Texto de la noticia a analizar"
          />
          <button 
            onClick={handleAnalyze} 
            disabled={loading}
            aria-busy={loading}
          >
            {loading ? (
              <>
                <Activity className="spinner" size={24} />
                Analizando...
              </>
            ) : (
              <>
                <ShieldAlert size={24} />
                Analizar Texto
              </>
            )}
          </button>
          
          {error && (
            <div className="error-message" role="alert">
              <AlertTriangle size={24} style={{ marginBottom: '-6px', marginRight: '8px' }} />
              {error}
            </div>
          )}
        </section>

        {results && (
          <section className="results-dashboard" aria-live="polite">
            <h2>Resultados del Análisis</h2>
            
            <div className="score-container">
              <div className={`trust-score ${getScoreClass(results.trustScore)}`}>
                {results.trustScore}%
              </div>
              <div className="score-label">Nivel de Confianza</div>
            </div>

            <div className="info-card" style={{ borderColor: 'var(--primary-color)' }}>
              <h3><Activity color="var(--primary-color)" /> Resumen del Análisis</h3>
              <p>{results.analysisSummary}</p>
            </div>

            <div className="info-card" style={{ borderColor: 'var(--warning-color)' }}>
              <h3><AlertTriangle color="var(--warning-color)" /> Sesgo Detectado</h3>
              <p><strong>{results.bias}</strong></p>
            </div>

            {results.redFlags && results.redFlags.length > 0 ? (
              <div className="info-card" style={{ borderColor: 'var(--danger-color)', backgroundColor: 'transparent', padding: 0, border: 'none' }}>
                <h3 style={{ marginBottom: '1rem' }}><ShieldAlert color="var(--danger-color)" /> Banderas Rojas (Señales de Alerta)</h3>
                <ul className="red-flags-list">
                  {results.redFlags.map((flag, index) => (
                    <li key={index}>
                      <AlertTriangle color="var(--danger-color)" size={24} style={{ flexShrink: 0 }} />
                      <span>{flag}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="info-card" style={{ borderColor: 'var(--success-color)' }}>
                <h3><CheckCircle color="var(--success-color)" /> Banderas Rojas</h3>
                <p>No se encontraron señales de alerta importantes.</p>
              </div>
            )}
          </section>
        )}
      </main>
    </div>
  );
}

export default App;
