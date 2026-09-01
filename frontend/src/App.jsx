import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import {
  Database,
  Download,
  ExternalLink,
  FileText,
  FlaskConical,
  Search,
  TableProperties
} from "lucide-react";
import {
  fetchDownloads,
  fetchFacets,
  fetchLatestRelease,
  fetchMeasurement,
  fetchMeasurements,
  fetchReleases,
  fetchStats
} from "./api";

const catlogUrl = "https://chowdhurylab.github.io/tools/catlog-static/";
const chowdhuryLabUrl = "https://chowdhurylab.github.io/";
const realKcatDoi = "https://doi.org/10.1101/2025.02.10.637555";

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "n/a";
  return Number(value).toLocaleString();
}

function formatMetric(metric) {
  if (!metric || !metric.available) return "Not reported";
  return `${metric.value} ${metric.unit || ""}`.trim();
}

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "pending";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function useAsync(factory, deps) {
  const [state, setState] = useState({ loading: true, error: "", data: null });

  useEffect(() => {
    let active = true;
    setState((current) => ({ ...current, loading: true, error: "" }));
    factory()
      .then((data) => {
        if (active) setState({ loading: false, error: "", data });
      })
      .catch((error) => {
        if (active) {
          setState({
            loading: false,
            error: error?.response?.data?.detail || error.message || "Request failed",
            data: null
          });
        }
      });
    return () => {
      active = false;
    };
  }, deps);

  return state;
}

function Layout() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          <Database size={22} aria-hidden="true" />
          <span>OpenKinetics Data</span>
        </Link>
        <nav className="navlinks" aria-label="Primary navigation">
          <NavLink to="/">Search</NavLink>
          <NavLink to="/downloads">Downloads</NavLink>
          <NavLink to="/releases">Releases</NavLink>
          <NavLink to="/citation">Citation</NavLink>
          <NavLink to="/api-docs">API</NavLink>
        </nav>
      </header>
      <AttributionBanner />
      <main>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/records/:recordKey" element={<RecordPage />} />
          <Route path="/downloads" element={<DownloadsPage />} />
          <Route path="/releases" element={<ReleasesPage />} />
          <Route path="/citation" element={<CitationPage />} />
          <Route path="/api-docs" element={<ApiDocsPage />} />
        </Routes>
      </main>
      <footer className="footer">
        <span>
          CatLog data from <a href={chowdhuryLabUrl}>Chowdhury Lab</a> collaborators.
        </span>
        <a href={catlogUrl}>CatLog static browser</a>
        <a href="https://predictor.openkinetics.org">Kinetics predictor</a>
      </footer>
    </div>
  );
}

function AttributionBanner() {
  return (
    <section className="catlog-banner">
      <div>
        <strong>CatLog-powered data portal.</strong> This resource is built from CatLog, developed
        by the <a href={chowdhuryLabUrl}>Chowdhury Lab</a> and collaborators. The full CatLog paper
        is coming soon; for now cite RealKcat.
      </div>
      <div className="banner-actions">
        <a href={catlogUrl}>
          CatLog <ExternalLink size={15} aria-hidden="true" />
        </a>
        <a href={realKcatDoi}>
          DOI <ExternalLink size={15} aria-hidden="true" />
        </a>
      </div>
    </section>
  );
}

function SearchPage() {
  const stats = useAsync(fetchStats, []);
  const facets = useAsync(fetchFacets, []);
  const [filters, setFilters] = useState({
    q: "",
    ec_class: "",
    source_db: "",
    verification_status: "",
    has_kcat: "",
    has_km: "",
    wild_type: ""
  });
  const [page, setPage] = useState(1);

  const query = useMemo(
    () => ({
      ...filters,
      page,
      page_size: 25
    }),
    [filters, page]
  );
  const measurements = useAsync(() => fetchMeasurements(query), [query]);

  function updateFilter(key, value) {
    setPage(1);
    setFilters((current) => ({ ...current, [key]: value }));
  }

  const facetData = facets.data?.facets || {};

  return (
    <div className="page">
      <StatsBar stats={stats.data} loading={stats.loading} />
      <section className="search-layout">
        <aside className="filters-panel">
          <div className="filter-heading">
            <Search size={18} aria-hidden="true" />
            <span>Search</span>
          </div>
          <label>
            Query
            <input
              value={filters.q}
              onChange={(event) => updateFilter("q", event.target.value)}
              placeholder="enzyme, substrate, EC, UniProt"
            />
          </label>
          <label>
            EC class
            <select
              value={filters.ec_class}
              onChange={(event) => updateFilter("ec_class", event.target.value)}
            >
              <option value="">All</option>
              {(facetData.ec_classes || []).map((row) => (
                <option key={row.ec_class} value={row.ec_class}>
                  {row.ec_class} ({row.count})
                </option>
              ))}
            </select>
          </label>
          <label>
            Source DB
            <select
              value={filters.source_db}
              onChange={(event) => updateFilter("source_db", event.target.value)}
            >
              <option value="">All</option>
              {(facetData.source_dbs || []).map((row) => (
                <option key={row.source_db} value={row.source_db}>
                  {row.source_db} ({row.count})
                </option>
              ))}
            </select>
          </label>
          <label>
            Status
            <select
              value={filters.verification_status}
              onChange={(event) => updateFilter("verification_status", event.target.value)}
            >
              <option value="">All</option>
              {(facetData.verification_statuses || []).map((row) => (
                <option key={row.verification_status} value={row.verification_status}>
                  {row.verification_status} ({row.count})
                </option>
              ))}
            </select>
          </label>
          <label>
            kcat
            <select value={filters.has_kcat} onChange={(event) => updateFilter("has_kcat", event.target.value)}>
              <option value="">Any</option>
              <option value="true">Available</option>
              <option value="false">Not reported</option>
            </select>
          </label>
          <label>
            Km
            <select value={filters.has_km} onChange={(event) => updateFilter("has_km", event.target.value)}>
              <option value="">Any</option>
              <option value="true">Available</option>
              <option value="false">Not reported</option>
            </select>
          </label>
          <label>
            Variant
            <select
              value={filters.wild_type}
              onChange={(event) => updateFilter("wild_type", event.target.value)}
            >
              <option value="">Any</option>
              <option value="true">Wild type</option>
              <option value="false">Mutant</option>
            </select>
          </label>
        </aside>
        <section className="results-panel">
          <div className="table-toolbar">
            <div>
              <h1>Browse measurements</h1>
              <p>{measurements.data?.pagination?.total || 0} records in the active release</p>
            </div>
            <Link className="icon-button primary" to="/downloads">
              <Download size={17} aria-hidden="true" />
              Downloads
            </Link>
          </div>
          {measurements.error ? <div className="alert-box">{measurements.error}</div> : null}
          <MeasurementTable loading={measurements.loading} data={measurements.data} />
          <Pagination
            pagination={measurements.data?.pagination}
            onPage={(nextPage) => setPage(nextPage)}
          />
        </section>
      </section>
    </div>
  );
}

function StatsBar({ stats, loading }) {
  const counts = stats?.counts || {};
  const release = stats?.release;
  const items = [
    ["Measurements", counts.measurements],
    ["Sequences", counts.sequences],
    ["Substrates", counts.substrates],
    ["EC numbers", counts.ec_numbers],
    ["kcat + Km", counts.rows_with_both_kcat_and_km]
  ];
  return (
    <section className="stats-band">
      <div className="release-chip">
        <FlaskConical size={17} aria-hidden="true" />
        <span>{release?.release_id || (loading ? "Loading release" : "No release")}</span>
      </div>
      {items.map(([label, value]) => (
        <div className="stat-item" key={label}>
          <span>{label}</span>
          <strong>{loading ? "..." : formatNumber(value)}</strong>
        </div>
      ))}
    </section>
  );
}

function MeasurementTable({ loading, data }) {
  const rows = data?.results || [];
  if (loading) return <div className="table-state">Loading measurements...</div>;
  if (!rows.length) return <div className="table-state">No matching measurements.</div>;
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Enzyme</th>
            <th>EC</th>
            <th>Organism</th>
            <th>Substrate</th>
            <th>kcat</th>
            <th>Km</th>
            <th>UniProt</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.record_key}>
              <td>
                <Link to={`/records/${row.record_key}`}>{row.enzyme_name}</Link>
              </td>
              <td>{row.ec_number}</td>
              <td>{row.organism}</td>
              <td>{row.substrate_name}</td>
              <td>{formatMetric(row.kcat)}</td>
              <td>{formatMetric(row.km)}</td>
              <td>{row.primary_uniprot_id}</td>
              <td>
                <span className={`status-pill status-${row.verification_status}`}>
                  {row.verification_status}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pagination({ pagination, onPage }) {
  if (!pagination || pagination.pages <= 1) return null;
  return (
    <div className="pagination-row">
      <button disabled={!pagination.has_previous} onClick={() => onPage(pagination.page - 1)}>
        Previous
      </button>
      <span>
        Page {pagination.page} of {pagination.pages}
      </span>
      <button disabled={!pagination.has_next} onClick={() => onPage(pagination.page + 1)}>
        Next
      </button>
    </div>
  );
}

function RecordPage() {
  const { recordKey } = useParams();
  const record = useAsync(() => fetchMeasurement(recordKey), [recordKey]);

  if (record.loading) return <div className="page"><div className="table-state">Loading record...</div></div>;
  if (record.error) return <div className="page"><div className="alert-box">{record.error}</div></div>;

  const row = record.data;
  return (
    <div className="page detail-page">
      <div className="detail-header">
        <div>
          <Link className="back-link" to="/">Back to search</Link>
          <h1>{row.enzyme.name}</h1>
          <p>{row.substrate.name} · {row.enzyme.organism} · EC {row.enzyme.ec_number}</p>
        </div>
        <span className={`status-pill status-${row.evidence.verification_status}`}>
          {row.evidence.verification_status}
        </span>
      </div>

      <section className="detail-grid">
        <Panel title="Measurements">
          <table className="compact-table">
            <tbody>
              <tr><th>kcat</th><td>{formatMetric(row.kcat)}</td></tr>
              <tr><th>Km</th><td>{formatMetric(row.km)}</td></tr>
              <tr><th>Ki</th><td>{formatMetric(row.ki)}</td></tr>
              <tr><th>kcat / Km</th><td>{formatMetric(row.kcat_over_km)}</td></tr>
              <tr><th>pH</th><td>{formatNumber(row.assay_conditions.ph)}</td></tr>
              <tr><th>Temperature</th><td>{formatNumber(row.assay_conditions.temperature_c)} C</td></tr>
            </tbody>
          </table>
        </Panel>

        <Panel title="Provenance">
          <dl className="key-values">
            <dt>Record key</dt><dd>{row.record_key}</dd>
            <dt>Source DB</dt><dd>{row.provenance.source_db}</dd>
            <dt>Evidence tier</dt><dd>{row.evidence.evidence_confidence_tier}</dd>
            <dt>Paper grounding</dt><dd>{row.evidence.paper_grounding_status}</dd>
            <dt>Literature counts</dt><dd>{row.provenance.pmid_count} PMID · {row.provenance.doi_count} DOI</dd>
          </dl>
          <p className="evidence-note">{row.evidence.compact_evidence_summary}</p>
        </Panel>

        <Panel title="Protein sequence">
          <dl className="key-values">
            <dt>Sequence ID</dt><dd>{row.sequence.sequence_id}</dd>
            <dt>UniProt</dt>
            <dd>
              <a href={row.sequence.source_url}>{row.enzyme.primary_uniprot_id}</a>
            </dd>
            <dt>Length</dt><dd>{row.sequence.length} aa</dd>
            <dt>Variant</dt><dd>{row.sequence.sequence_variant_status}</dd>
          </dl>
          <pre className="sequence-block">{row.sequence.sequence}</pre>
        </Panel>

        <Panel title="Sequence artifacts">
          <div className="artifact-list">
            {(row.sequence_artifacts || []).map((artifact) => (
              <article className="artifact-row" key={artifact.artifact_key}>
                <div>
                  <h3>{artifact.label}</h3>
                  <p>{artifact.description}</p>
                  <small>
                    {artifact.available
                      ? `${formatBytes(artifact.size_bytes)} · ${artifact.relative_path}`
                      : `Awaiting ${artifact.sequence_id}.npy`}
                  </small>
                </div>
                {artifact.available ? (
                  <a className="icon-button" href={artifact.url}>
                    <Download size={16} aria-hidden="true" />
                    Download
                  </a>
                ) : (
                  <span className="pending-pill">Awaiting file</span>
                )}
              </article>
            ))}
          </div>
        </Panel>

        <Panel title="Substrate">
          <dl className="key-values">
            <dt>Substrate ID</dt><dd>{row.substrate.substrate_id}</dd>
            <dt>PubChem</dt>
            <dd>
              <a href={row.substrate.source_url}>{row.substrate.pubchem_cid}</a>
            </dd>
            <dt>InChIKey</dt><dd>{row.substrate.inchi_key}</dd>
            <dt>Formula</dt><dd>{row.substrate.molecular_formula}</dd>
          </dl>
          <code className="smiles-line">{row.substrate.smiles}</code>
        </Panel>
      </section>
    </div>
  );
}

function Panel({ title, children }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function DownloadsPage() {
  const downloads = useAsync(fetchDownloads, []);
  const groups = downloads.data?.groups || {};
  const order = ["bundles", "measurements", "sequences", "substrates", "splits", "embeddings", "pseq2sites", "metadata"];

  return (
    <div className="page">
      <div className="page-heading">
        <h1>Downloads</h1>
        <p>{downloads.data?.release?.release_id || "Active release"}</p>
      </div>
      {downloads.error ? <div className="alert-box">{downloads.error}</div> : null}
      {order.map((family) => (
        groups[family]?.length ? <ArtifactGroup key={family} title={family} artifacts={groups[family]} /> : null
      ))}
    </div>
  );
}

function ArtifactGroup({ title, artifacts }) {
  return (
    <section className="download-section">
      <h2>{title.replaceAll("_", " ")}</h2>
      <div className="download-list">
        {artifacts.map((artifact) => (
          <article className="download-row" key={artifact.artifact_key}>
            <div>
              <h3>{artifact.label}</h3>
              <p>{artifact.description}</p>
              <small>{formatBytes(artifact.size_bytes)} · {artifact.sha256 ? artifact.sha256.slice(0, 12) : "checksum pending"}</small>
            </div>
            {artifact.available ? (
              <a className="icon-button" href={artifact.url}>
                <Download size={16} aria-hidden="true" />
                Download
              </a>
            ) : (
              <span className="pending-pill">Awaiting file</span>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function ReleasesPage() {
  const releases = useAsync(fetchReleases, []);
  const latest = useAsync(fetchLatestRelease, []);
  return (
    <div className="page">
      <div className="page-heading">
        <h1>Releases</h1>
        <p>Immutable data versions with checksums and release manifests.</p>
      </div>
      <section className="panel wide-panel">
        <h2>Latest manifest</h2>
        {latest.data ? (
          <pre className="manifest-block">{JSON.stringify(latest.data.manifest, null, 2)}</pre>
        ) : (
          <div className="table-state">Loading manifest...</div>
        )}
      </section>
      <section className="download-section">
        <h2>Version history</h2>
        <div className="download-list">
          {(releases.data || []).map((release) => (
            <article className="download-row" key={release.release_id}>
              <div>
                <h3>{release.release_id}</h3>
                <p>{release.title}</p>
              </div>
              <span className="status-pill">{release.record_count} records</span>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function CitationPage() {
  return (
    <div className="page text-page">
      <h1>Citation and Attribution</h1>
      <section className="panel wide-panel">
        <h2>CatLog</h2>
        <p>
          This data resource is built from CatLog, developed by the{" "}
          <a href={chowdhuryLabUrl}>Chowdhury Lab</a> and collaborators. The full CatLog publication
          is coming soon.
        </p>
        <p>
          CatLog static browser: <a href={catlogUrl}>{catlogUrl}</a>
        </p>
      </section>
      <section className="panel wide-panel">
        <h2>Current Citation</h2>
        <p>
          Sajeevan et al., Robust Prediction of Enzyme Variant Kinetics with RealKcat,
          bioRxiv 2025.
        </p>
        <p>
          DOI: <a href={realKcatDoi}>{realKcatDoi}</a>
        </p>
      </section>
      <section className="panel wide-panel">
        <h2>OpenKinetics</h2>
        <p>Data curated by CatLog collaborators, served by OpenKinetics.</p>
      </section>
    </div>
  );
}

function ApiDocsPage() {
  return (
    <div className="page text-page">
      <h1>API</h1>
      <section className="panel wide-panel">
        <h2>Endpoints</h2>
        <pre className="code-block">{`GET /api/stats/
GET /api/measurements/?q=kinase&has_kcat=true
GET /api/measurements/{record_key}/
GET /api/downloads/
GET /api/releases/latest/`}</pre>
      </section>
      <section className="panel wide-panel">
        <h2>Python</h2>
        <pre className="code-block">{`import requests

records = requests.get(
    "https://data.openkinetics.org/api/measurements/",
    params={"q": "ATP", "has_km": "true"},
).json()`}</pre>
      </section>
    </div>
  );
}

export default function App() {
  return <Layout />;
}
