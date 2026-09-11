import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileText,
  FlaskConical,
  Search
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
const openKineticsUrl = "https://openkinetics.org/";
const realKcatDoi = "https://doi.org/10.1101/2025.02.10.637555";
const realKcatBibtex = String.raw`@article{sajeevan2025robust,
  author = {Sajeevan, Karuna Anna and Osinuga, Abraham and Arunraj, B and Ferdous, Sakib and Shahreen, Nabia and Noor, Mohammed Sakib and Koneru, Shashank and Santos-Correa, Laura Mariana and Salehi, Rahil and Chowdhury, Niaz Bahar and Aryee, Randy and Calderon-Lopez, Brisa and Mali, Ankur and Saha, Rajib and Chowdhury, Ratul},
  title = {{Robust Prediction of Enzyme Variant Kinetics with RealKcat}},
  journal = {bioRxiv},
  year = {2025},
  note = {Preprint},
  doi = {10.1101/2025.02.10.637555},
  url = {https://doi.org/10.1101/2025.02.10.637555}
}`;
const openKineticsBibtex = String.raw`@unpublished{alwer2026accessing,
  author = {Alwer, Saleh and Escoffier, Hugues and Taha, Karim and Boorla, Veda and Yu, Han and Santra, Somtirtha and Wang, Zechen and Egwu, Chidi and Osinuga, Abraham and Dey, Supantha and Srinivasan Raghunath, Vaishnavey and Zare, Farid and McGoldrick, Jack and Weder, Jan-Niklas and Kerkhoven, Eduard and Luo, Xiaozhou and Maranas, Costas D. and Zheng, Liangzhen and Wittig, Ulrike and Chowdhury, Ratul and Saha, Rajib and T{\"o}pfer, Nadine and Sauter, Thomas and Fleming, Ronan M. T.},
  title = {{Accessing Enzyme Kinetic Data and Prediction Methods at Scale}},
  note = {Unpublished manuscript},
  year = {2026}
}`;

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "n/a";
  return Number(value).toLocaleString();
}

function formatMetric(metric) {
  if (!metric || !metric.available) return "Not reported";
  return `${metric.value} ${metric.unit || ""}`.trim();
}

function formatText(value) {
  if (value === null || value === undefined || value === "") return "n/a";
  return value;
}

function formatBool(value) {
  if (value === true) return "Yes";
  if (value === false) return "No";
  return "n/a";
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

function formatScore(value) {
  if (typeof value !== "number") return "n/a";
  return value.toFixed(3);
}

function artifactInputTokens(sequence, generation = {}) {
  const residues = sequence ? sequence.split("") : [];
  if (!generation.input_sequence_was_truncated) {
    return residues.map((residue, index) => ({
      residue,
      originalPosition: index + 1,
      scoreIndex: index
    }));
  }
  const nTerminal = generation.truncation_n_terminal_residues || 512;
  const cTerminal = generation.truncation_c_terminal_residues || 512;
  const tailStart = Math.max(residues.length - cTerminal, nTerminal);
  const omitted = Math.max(tailStart - nTerminal, 0);
  return [
    ...residues.slice(0, nTerminal).map((residue, index) => ({
      residue,
      originalPosition: index + 1,
      scoreIndex: index
    })),
    { gap: true, omitted },
    ...residues.slice(tailStart).map((residue, index) => ({
      residue,
      originalPosition: tailStart + index + 1,
      scoreIndex: nTerminal + index
    }))
  ];
}

function enzymeIdentityKey(row) {
  return [
    row.enzyme_name || row.enzyme?.name || "",
    row.ec_number || row.enzyme?.ec_number || "",
    row.organism || row.enzyme?.organism || "",
    row.primary_uniprot_id || row.enzyme?.primary_uniprot_id || ""
  ].join("\u001f");
}

function enzymeIdentityQuery(row, page = 1) {
  const primaryUniprotId = row.primary_uniprot_id || row.enzyme?.primary_uniprot_id || "";
  return {
    enzyme_identity: "true",
    enzyme_name: row.enzyme_name || row.enzyme?.name || "",
    ec_number_exact: row.ec_number || row.enzyme?.ec_number || "",
    organism_exact: row.organism || row.enzyme?.organism || "",
    uniprot: primaryUniprotId,
    page,
    page_size: 100
  };
}

function statLabel(key) {
  return key
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function absoluteUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  if (typeof window === "undefined") return url;
  return `${window.location.origin}${url.startsWith("/") ? "" : "/"}${url}`;
}

function residueScoreStyle(score) {
  if (typeof score !== "number") return undefined;
  const value = Math.max(0, Math.min(1, score));
  if (value >= 0.75) return { backgroundColor: "#b91c1c", color: "#fff" };
  if (value >= 0.5) return { backgroundColor: "#f97316", color: "#231407" };
  if (value >= 0.25) return { backgroundColor: "#fde68a", color: "#27200a" };
  return { backgroundColor: "#dbeafe", color: "#10233f" };
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
        <Link className="brand" to="/downloads">
          <Database size={22} aria-hidden="true" />
          <span>OpenKinetics Data</span>
        </Link>
        <nav className="navlinks" aria-label="Primary navigation">
          <NavLink to="/downloads">Downloads</NavLink>
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/releases">Releases</NavLink>
          <NavLink to="/citation">Citation</NavLink>
          <NavLink to="/api-docs">API</NavLink>
        </nav>
      </header>
      <AttributionBanner />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/downloads" replace />} />
          <Route path="/search" element={<SearchPage />} />
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
  const [expandedRecordKey, setExpandedRecordKey] = useState("");
  const [enzymePanel, setEnzymePanel] = useState(null);

  function toggleMeasurement(row) {
    setExpandedRecordKey((current) => (current === row.record_key ? "" : row.record_key));
    setEnzymePanel(null);
  }

  function toggleEnzymePanel(event, row) {
    event.stopPropagation();
    const key = enzymeIdentityKey(row);
    setExpandedRecordKey("");
    setEnzymePanel((current) => (
      current?.key === key && current?.anchorRecordKey === row.record_key
        ? null
        : { key, anchorRecordKey: row.record_key, row }
    ));
  }

  function handleRowKeyDown(event, row) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggleMeasurement(row);
  }

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
          {rows.map((row) => {
            const measurementExpanded = expandedRecordKey === row.record_key;
            const enzymeExpanded = enzymePanel?.anchorRecordKey === row.record_key;
            return (
              <Fragment key={row.record_key}>
                <tr
                  className={`measurement-row ${measurementExpanded || enzymeExpanded ? "is-expanded" : ""}`}
                  role="button"
                  tabIndex={0}
                  aria-expanded={measurementExpanded || enzymeExpanded}
                  onClick={() => toggleMeasurement(row)}
                  onKeyDown={(event) => handleRowKeyDown(event, row)}
                >
                  <td>
                    <div className="enzyme-cell">
                      {measurementExpanded ? (
                        <ChevronDown size={16} aria-hidden="true" />
                      ) : (
                        <ChevronRight size={16} aria-hidden="true" />
                      )}
                      <button
                        type="button"
                        className="link-button"
                        onClick={(event) => toggleEnzymePanel(event, row)}
                      >
                        {row.enzyme_name}
                      </button>
                    </div>
                  </td>
                  <td>{row.ec_number}</td>
                  <td>{row.organism}</td>
                  <td>{row.substrate_name}</td>
                  <td>{formatMetric(row.kcat)}</td>
                  <td>{formatMetric(row.km)}</td>
                  <td>{formatText(row.primary_uniprot_id)}</td>
                  <td>
                    <span className={`status-pill status-${row.verification_status}`}>
                      {row.verification_status}
                    </span>
                  </td>
                </tr>
                {measurementExpanded ? (
                  <tr className="expanded-row">
                    <td colSpan={8}>
                      <MeasurementInlineDetail recordKey={row.record_key} />
                    </td>
                  </tr>
                ) : null}
                {enzymeExpanded ? (
                  <tr className="expanded-row">
                    <td colSpan={8}>
                      <EnzymeMeasurementsPanel row={enzymePanel.row} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MeasurementInlineDetail({ recordKey }) {
  const record = useAsync(() => fetchMeasurement(recordKey), [recordKey]);

  if (record.loading) return <div className="table-state compact-state">Loading measurement...</div>;
  if (record.error) return <div className="alert-box compact-state">{record.error}</div>;
  return <MeasurementDetailPanels row={record.data} embedded />;
}

function EnzymeMeasurementsPanel({ row }) {
  const [page, setPage] = useState(1);
  const [expandedRecordKey, setExpandedRecordKey] = useState("");
  const query = useMemo(() => enzymeIdentityQuery(row, page), [row, page]);
  const measurements = useAsync(() => fetchMeasurements(query), [query]);
  const rows = measurements.data?.results || [];

  function toggleRecord(recordKey) {
    setExpandedRecordKey((current) => (current === recordKey ? "" : recordKey));
  }

  return (
    <section className="enzyme-panel">
      <div className="enzyme-panel-header">
        <div>
          <h2>{row.enzyme_name}</h2>
          <p>
            {formatText(row.organism)} · EC {formatText(row.ec_number)} · {formatText(row.primary_uniprot_id)}
          </p>
        </div>
        <span className="status-pill">
          {formatNumber(measurements.data?.pagination?.total || 0)} measurements
        </span>
      </div>
      {measurements.error ? <div className="alert-box compact-state">{measurements.error}</div> : null}
      {measurements.loading ? <div className="table-state compact-state">Loading enzyme measurements...</div> : null}
      {!measurements.loading && rows.length ? (
        <div className="compact-table-wrap">
          <table className="compact-measurement-table">
            <thead>
              <tr>
                <th>Substrate</th>
                <th>kcat</th>
                <th>Km</th>
                <th>Variant</th>
                <th>Status</th>
                <th>Record</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((measurement) => (
                <CompactMeasurementRow
                  expanded={expandedRecordKey === measurement.record_key}
                  key={measurement.record_key}
                  measurement={measurement}
                  onToggle={() => toggleRecord(measurement.record_key)}
                />
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {!measurements.loading && !rows.length && !measurements.error ? (
        <div className="table-state compact-state">No measurements found.</div>
      ) : null}
      <Pagination
        pagination={measurements.data?.pagination}
        onPage={(nextPage) => {
          setExpandedRecordKey("");
          setPage(nextPage);
        }}
      />
    </section>
  );
}

function CompactMeasurementRow({ measurement, expanded, onToggle }) {
  function handleKeyDown(event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    onToggle();
  }

  return (
    <Fragment>
      <tr
        className={`measurement-row compact-row ${expanded ? "is-expanded" : ""}`}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggle}
        onKeyDown={handleKeyDown}
      >
        <td>{measurement.substrate_name}</td>
        <td>{formatMetric(measurement.kcat)}</td>
        <td>{formatMetric(measurement.km)}</td>
        <td>{measurement.is_mutant ? formatText(measurement.mutation_signature) : "Wild type"}</td>
        <td>
          <span className={`status-pill status-${measurement.verification_status}`}>
            {measurement.verification_status}
          </span>
        </td>
        <td><code>{measurement.record_key}</code></td>
      </tr>
      {expanded ? (
        <tr className="expanded-row">
          <td colSpan={6}>
            <MeasurementInlineDetail recordKey={measurement.record_key} />
          </td>
        </tr>
      ) : null}
    </Fragment>
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
          <Link className="back-link" to="/search">Back to search</Link>
          <h1>{row.enzyme.name}</h1>
          <p>{row.substrate.name} · {row.enzyme.organism} · EC {row.enzyme.ec_number}</p>
        </div>
        <span className={`status-pill status-${row.evidence.verification_status}`}>
          {row.evidence.verification_status}
        </span>
      </div>

      <MeasurementDetailPanels row={row} />
    </div>
  );
}

function MeasurementDetailPanels({ row, embedded = false }) {
  return (
    <section className={`detail-grid ${embedded ? "inline-detail-grid" : ""}`}>
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

      <ProteinSequencePanel row={row} />

      <Panel title="Sequence artifacts">
        <div className="artifact-list">
          {(row.sequence_artifacts || []).map((artifact) => (
            <article className="artifact-row" key={artifact.artifact_key}>
              <div>
                <h3>{artifact.label}</h3>
                <p>{artifact.description}</p>
                {artifact.sequence_artifact_input_was_truncated ? (
                  <p className="artifact-note">
                    <AlertTriangle size={14} aria-hidden="true" />
                    Generated from first 512 + last 512 residues; saved under the original sequence ID.
                  </p>
                ) : null}
                <small>
                  {artifact.available
                    ? `${formatBytes(artifact.size_bytes)} · ${artifact.relative_path}`
                    : `Awaiting ${artifact.source_filename || `${artifact.sequence_id}.npy`}`}
                </small>
              </div>
              {artifact.available ? (
                <a className="icon-button" href={artifact.url}>
                  <Download size={16} aria-hidden="true" />
                  Download ZIP
                </a>
              ) : (
                <span className="pending-pill">Awaiting file</span>
              )}
              <DownloadFormatDetails artifact={artifact} />
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Substrate">
        <dl className="key-values">
          <dt>Substrate ID</dt><dd>{row.substrate.substrate_id}</dd>
          <dt>PubChem</dt>
          <dd>
            {row.substrate.pubchem_cid ? (
              <a href={row.substrate.source_url}>{row.substrate.pubchem_cid}</a>
            ) : (
              "n/a"
            )}
          </dd>
          <dt>InChIKey</dt><dd>{formatText(row.substrate.inchi_key)}</dd>
          <dt>Formula</dt><dd>{formatText(row.substrate.molecular_formula)}</dd>
        </dl>
        <code className="smiles-line">{row.substrate.smiles}</code>
      </Panel>
    </section>
  );
}

function ProteinSequencePanel({ row }) {
  const sequence = row.sequence || {};
  const artifactGeneration = sequence.sequence_artifact_generation || {};
  return (
    <Panel title="Protein sequence">
      <dl className="key-values">
        <dt>Sequence ID</dt><dd>{sequence.sequence_id}</dd>
        <dt>UniProt</dt>
        <dd>
          {row.enzyme.primary_uniprot_id && sequence.source_url ? (
            <a href={sequence.source_url}>{row.enzyme.primary_uniprot_id}</a>
          ) : (
            formatText(row.enzyme.primary_uniprot_id)
          )}
        </dd>
        <dt>Length</dt><dd>{sequence.length} aa</dd>
        <dt>Mutant</dt><dd>{formatBool(sequence.is_mutant)}</dd>
        <dt>Wild type</dt><dd>{formatBool(sequence.wild_type)}</dd>
        <dt>Mutation</dt><dd>{formatText(sequence.mutation_signature)}</dd>
        <dt>Mutation type</dt><dd>{formatText(sequence.mutation_type)}</dd>
        <dt>Variant status</dt><dd>{formatText(sequence.sequence_variant_status)}</dd>
        <dt>Assayed sequence</dt><dd>{formatText(sequence.assayed_sequence_source)}</dd>
        <dt>Artifact input</dt>
        <dd>
          {artifactGeneration.input_sequence_was_truncated
            ? `${formatNumber(artifactGeneration.input_sequence_length)} aa from first 512 + last 512`
            : `${formatNumber(artifactGeneration.input_sequence_length || sequence.length)} aa full sequence`}
        </dd>
      </dl>
      {artifactGeneration.input_sequence_was_truncated ? (
        <p className="truncation-note">
          <AlertTriangle size={15} aria-hidden="true" />
          Sequence artifacts use the first 512 and last 512 residues as model input. Arrays remain keyed by the original sequence ID.
        </p>
      ) : null}
      {sequence.sequence_variant_note ? (
        <p className="evidence-note">{sequence.sequence_variant_note}</p>
      ) : null}
      <SequenceTextDetails title="Wild-type sequence" sequence={sequence.wild_type_sequence} />
      <SequenceTextDetails title="Variant sequence" sequence={sequence.variant_sequence} />
      <BindingSiteLegend prediction={row.binding_site_prediction} />
      <SequenceHeatmap
        prediction={row.binding_site_prediction}
        sequence={sequence.sequence}
      />
    </Panel>
  );
}

function SequenceTextDetails({ title, sequence }) {
  if (!sequence) return null;
  return (
    <details className="sequence-details">
      <summary>{title}</summary>
      <pre className="sequence-block">{sequence}</pre>
    </details>
  );
}

function BindingSiteLegend({ prediction }) {
  const available = prediction?.available && prediction?.scores?.length;
  const generation = prediction?.sequence_artifact_generation || {};
  if (!available) {
    return (
      <div className="binding-site-summary muted">
        <strong>Pseq2Sites binding-site likelihood</strong>
        <span>{prediction?.message || "Scores are not available for this sequence."}</span>
      </div>
    );
  }
  const summary = prediction.summary || {};
  const alignment = generation.input_sequence_was_truncated
    ? `${prediction.score_count} scores for ${prediction.sequence_artifact_input_length} residue artifact input from ${prediction.residue_count} residues`
    : prediction.aligned_to_sequence
    ? `${prediction.score_count} scores aligned to ${prediction.residue_count} residues`
    : `${prediction.score_count} scores for ${prediction.residue_count} residues`;
  return (
    <div className="binding-site-summary">
      <div>
        <strong>Pseq2Sites binding-site likelihood</strong>
        <span>{alignment}</span>
      </div>
      <div className="score-legend" aria-label="Binding-site likelihood scale">
        <span>Low</span>
        <div className="score-ramp" />
        <span>High</span>
      </div>
      <dl className="score-stats">
        <dt>Mean</dt><dd>{formatScore(summary.mean)}</dd>
        <dt>Max</dt><dd>{formatScore(summary.max)}</dd>
      </dl>
    </div>
  );
}

function SequenceHeatmap({ sequence, prediction }) {
  const scores = prediction?.scores || [];
  const hasScores = prediction?.available && scores.length > 0;
  const tokens = artifactInputTokens(
    sequence,
    hasScores ? prediction?.sequence_artifact_generation || {} : {}
  );
  return (
    <div
      className={`sequence-heatmap ${hasScores ? "" : "sequence-heatmap-plain"}`}
      aria-label="Protein sequence colored by Pseq2Sites binding-site likelihood"
    >
      {tokens.map((token, index) => {
        if (token.gap) {
          return (
            <span className="residue-gap" key={`gap-${index}`}>
              {formatNumber(token.omitted)} omitted
            </span>
          );
        }
        const score = typeof scores[token.scoreIndex] === "number" ? scores[token.scoreIndex] : null;
        const title = score === null
          ? `Residue ${token.originalPosition}: ${token.residue}`
          : `Residue ${token.originalPosition}: ${token.residue}, Pseq2Sites ${formatScore(score)}`;
        return (
          <span
            className="residue-token"
            key={`${index}-${token.originalPosition}-${token.residue}`}
            style={hasScores ? residueScoreStyle(score) : undefined}
            title={title}
          >
            {token.residue}
          </span>
        );
      })}
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
      <DownloadStatsPanel stats={downloads.data?.stats} loading={downloads.loading} />
      {order.map((family) => (
        groups[family]?.length ? <ArtifactGroup key={family} title={family} artifacts={groups[family]} /> : null
      ))}
    </div>
  );
}

function DownloadStatsPanel({ stats, loading }) {
  const [expanded, setExpanded] = useState(false);
  const releaseCounts = stats?.counts || {};
  const counts = visibleReleaseCounts(releaseCounts);
  const rejectedRows = stats?.eligibility?.rejected_rows_by_reason || {};
  const compactItems = [
    ["Datapoints", counts.datapoints],
    ["Sequences", counts.unique_sequences],
    ["Substrates", counts.unique_substrates],
    ["EC numbers", counts.unique_ec_numbers],
    ["Mutant rows", releaseCounts.mutant_rows ?? releaseCounts.rows_marked_mutant],
    ["Truncated inputs", counts.sequences_with_truncated_artifact_input]
  ];

  return (
    <section className="download-stats">
      <button
        type="button"
        className="download-stats-header"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <span>
          {expanded ? <ChevronDown size={18} aria-hidden="true" /> : <ChevronRight size={18} aria-hidden="true" />}
          Release stats
        </span>
        <strong>{loading ? "..." : formatNumber(counts.datapoints)} datapoints</strong>
      </button>
      <div className="download-stat-grid">
        {compactItems.map(([label, value]) => (
          <div className="download-stat" key={label}>
            <span>{label}</span>
            <strong>{loading ? "..." : formatNumber(value)}</strong>
          </div>
        ))}
      </div>
      {expanded ? (
        <div className="download-stats-expanded">
          <div className="included-stats-grid">
            <SequenceRowSummary counts={releaseCounts} />
            <KineticCoverageVenn counts={releaseCounts} />
            <StatsBarChart
              title="Verification statuses"
              values={stats?.verification_status_counts || {}}
              colors={{
                corrected: "#547f73",
                manual_review_required: "#d39b3c",
                mathematically_inferred: "#4f78a8",
                unverified: "#89918e",
                verified: "#2f8a68"
              }}
            />
            <StatsBarChart
              title="Source DBs"
              values={stats?.source_db_counts || {}}
              colors={["#477a6b", "#4f78a8", "#bd8435", "#9a625c", "#6f7995", "#70924d"]}
            />
            <StatsKeyValueTable title="Included datapoint counts" values={counts} />
            <DistributionTable
              title="Enzyme datapoint distribution"
              rows={stats?.distributions?.enzyme_datapoints || []}
              countLabel="Enzymes"
            />
            <DistributionTable
              title="Substrate datapoint distribution"
              rows={stats?.distributions?.substrate_datapoints || []}
              countLabel="Substrates"
            />
            <TopListTable
              title="Top enzymes"
              rows={stats?.top_enzymes || []}
              labelKey="enzyme_name"
              secondary={(row) => `${formatText(row.organism)} · EC ${formatText(row.ec_number)} · ${formatText(row.primary_uniprot_id)}`}
            />
            <TopListTable
              title="Top substrates"
              rows={stats?.top_substrates || []}
              labelKey="substrate_name"
              secondary={(row) => row.substrate_id}
            />
          </div>
          <RejectedRowsPanel values={rejectedRows} />
        </div>
      ) : null}
    </section>
  );
}

function visibleReleaseCounts(counts) {
  const hiddenKeys = new Set([
    "rows_with_kcat",
    "rows_with_km",
    "rows_with_both_kcat_and_km",
    "mutant_rows",
    "mutant_rows_using_variant_sequence",
    "mutant_rows_without_variant_sequence",
    "rows_marked_mutant",
    "rows_with_variant_sequence",
    "rows_with_wild_type_sequence"
  ]);
  return Object.fromEntries(
    Object.entries(counts || {}).filter(([key]) => !hiddenKeys.has(key))
  );
}

function SequenceRowSummary({ counts }) {
  const mutantRows = counts.mutant_rows
    ?? counts.rows_marked_mutant
    ?? counts.mutant_rows_using_variant_sequence;
  const wildTypeSequenceRows = counts.rows_with_wild_type_sequence;
  if (mutantRows === undefined && wildTypeSequenceRows === undefined) return null;

  return (
    <section className="stats-subsection sequence-row-summary">
      <h2>Sequence coverage</h2>
      <div className="sequence-row-grid">
        <div>
          <span>Mutant Rows</span>
          <strong>{formatNumber(mutantRows)}</strong>
        </div>
        <div>
          <span>Rows With Wild Type Sequence</span>
          <strong>{formatNumber(wildTypeSequenceRows)}</strong>
        </div>
      </div>
    </section>
  );
}

function KineticCoverageVenn({ counts }) {
  const kcat = Number(counts.rows_with_kcat) || 0;
  const km = Number(counts.rows_with_km) || 0;
  const both = Math.min(Number(counts.rows_with_both_kcat_and_km) || 0, kcat, km);
  const kcatOnly = Math.max(kcat - both, 0);
  const kmOnly = Math.max(km - both, 0);
  const total = Number(counts.datapoints) || kcatOnly + both + kmOnly;
  const [activeKey, setActiveKey] = useState("both");

  if (!kcat && !km) return null;

  const regions = {
    kcatOnly: { label: "Kcat only", value: kcatOnly, color: "#4f927e" },
    both: { label: "Both Kcat and Km", value: both, color: "#477f83" },
    kmOnly: { label: "Km only", value: kmOnly, color: "#6e8fb5" }
  };
  const active = regions[activeKey];
  const activeShare = total ? `${((active.value / total) * 100).toFixed(1)}% of datapoints` : "";

  function regionProps(key) {
    const region = regions[key];
    return {
      className: `venn-region venn-${key} ${activeKey === key ? "active" : ""}`,
      role: "button",
      tabIndex: 0,
      "aria-label": `${region.label}: ${formatNumber(region.value)} rows`,
      "aria-pressed": activeKey === key,
      onClick: () => setActiveKey(key),
      onFocus: () => setActiveKey(key),
      onMouseEnter: () => setActiveKey(key),
      onKeyDown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setActiveKey(key);
        }
      }
    };
  }

  return (
    <section className="stats-subsection venn-panel">
      <div className="chart-heading">
        <h2>Kcat and Km coverage</h2>
        <span>{formatNumber(total)} rows</span>
      </div>
      <svg className="kinetic-venn" viewBox="0 0 360 180" aria-label="Kcat and Km datapoint overlap">
        <circle cx="120" cy="90" r="84" {...regionProps("kcatOnly")} />
        <circle cx="240" cy="90" r="84" {...regionProps("kmOnly")} />
        <path
          d="M 180 31.21 A 84 84 0 0 1 180 148.79 A 84 84 0 0 1 180 31.21"
          {...regionProps("both")}
        />
        <g className="venn-label" aria-hidden="true">
          <text x="93" y="84">Kcat only</text>
          <text className="venn-value" x="93" y="106">{formatNumber(kcatOnly)}</text>
        </g>
        <g className="venn-label" aria-hidden="true">
          <text x="180" y="84">Both</text>
          <text className="venn-value" x="180" y="106">{formatNumber(both)}</text>
        </g>
        <g className="venn-label" aria-hidden="true">
          <text x="267" y="84">Km only</text>
          <text className="venn-value" x="267" y="106">{formatNumber(kmOnly)}</text>
        </g>
      </svg>
      <div className="venn-detail" aria-live="polite">
        <span className="chart-swatch" style={{ backgroundColor: active.color }} />
        <span>{active.label}</span>
        <strong>{formatNumber(active.value)}</strong>
        <small>{activeShare}</small>
      </div>
    </section>
  );
}

function chartLabel(key) {
  const labels = {
    brenda: "BRENDA",
    oed: "OED",
    sabio_rk: "SABIO-RK",
    skid: "SKiD",
    uniprot: "UniProt"
  };
  return labels[key] || statLabel(key);
}

function StatsBarChart({ title, values, colors }) {
  const entries = Object.entries(values || {})
    .map(([key, value]) => [key, Number(value) || 0])
    .sort((left, right) => right[1] - left[1]);
  if (!entries.length) return null;

  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const maximum = Math.max(...entries.map(([, value]) => value), 1);

  return (
    <section className="stats-subsection bar-chart-panel">
      <div className="chart-heading">
        <h2>{title}</h2>
        <span>{formatNumber(total)} rows</span>
      </div>
      <div className="stats-bar-chart" role="list" aria-label={title}>
        {entries.map(([key, value], index) => {
          const label = chartLabel(key);
          const share = total ? `${((value / total) * 100).toFixed(1)}%` : "0%";
          return (
            <div
              className="stats-bar-row"
              key={key}
              role="listitem"
              tabIndex={0}
              title={`${label}: ${formatNumber(value)} rows (${share})`}
              style={{
                "--bar-color": Array.isArray(colors)
                  ? colors[index % colors.length]
                  : colors[key] || "#547f73",
                "--bar-width": `${(value / maximum) * 100}%`
              }}
            >
              <div className="stats-bar-label">
                <span>{label}</span>
                <strong>{formatNumber(value)}</strong>
              </div>
              <div className="stats-bar-track" aria-hidden="true">
                <span />
              </div>
              <small>{share}</small>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function StatsKeyValueTable({ title, values }) {
  const entries = Object.entries(values || {});
  if (!entries.length) return null;
  return (
    <section className="stats-subsection">
      <h2>{title}</h2>
      <div className="stats-kv-grid">
        {entries.map(([key, value]) => (
          <div key={key}>
            <span>{statLabel(key)}</span>
            <strong>{formatNumber(value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function RejectedRowsPanel({ values }) {
  const entries = Object.entries(values || {});
  if (!entries.length) return null;
  const total = entries.reduce((sum, [, value]) => sum + (Number(value) || 0), 0);
  return (
    <section className="rejected-rows-panel">
      <div className="rejected-rows-heading">
        <div>
          <h2>Rejected rows</h2>
          <p>
            Source rows rejected before release assembly. These rows are not included in
            the Datapoints count above.
          </p>
        </div>
        <span className="status-pill">{formatNumber(total)} outside release</span>
      </div>
      <div className="stats-kv-grid rejected-rows-grid">
        {entries.map(([key, value]) => (
          <div key={key}>
            <span>{statLabel(key)}</span>
            <strong>{formatNumber(value)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function DistributionTable({ title, rows, countLabel }) {
  if (!rows.length) return null;
  return (
    <section className="stats-subsection">
      <h2>{title}</h2>
      <table className="stats-table">
        <thead>
          <tr>
            <th>Datapoints</th>
            <th>{countLabel}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${title}-${row.bucket}`}>
              <td>{row.bucket}</td>
              <td>{formatNumber(row.count)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function TopListTable({ title, rows, labelKey, secondary }) {
  if (!rows.length) return null;
  return (
    <section className="stats-subsection">
      <h2>{title}</h2>
      <table className="stats-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Context</th>
            <th>Datapoints</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${title}-${row[labelKey]}-${secondary(row)}`}>
              <td>{row[labelKey]}</td>
              <td>{secondary(row)}</td>
              <td>{formatNumber(row.datapoints)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ArtifactGroup({ title, artifacts }) {
  return (
    <section className="download-section">
      <h2>{title.replaceAll("_", " ")}</h2>
      <div className="download-list">
        {artifacts.map((artifact) => <ArtifactDownloadRow artifact={artifact} key={artifact.artifact_key} />)}
      </div>
    </section>
  );
}

function ArtifactDownloadRow({ artifact }) {
  const isCommandPanel = artifact.metadata?.download_mode === "command_panel";
  return (
    <article className="download-row">
      <div className="download-row-copy">
        <h3>{artifact.label}</h3>
        <p>{artifact.description}</p>
        <small>
          {formatBytes(artifact.size_bytes)}
          {" · "}
          {artifact.sha256 ? artifact.sha256.slice(0, 12) : "checksum pending"}
          {artifact.metadata?.index_size_bytes ? ` · index ${formatBytes(artifact.metadata.index_size_bytes)}` : ""}
        </small>
      </div>
      {isCommandPanel ? (
        <EmbeddingCommandPanel artifact={artifact} />
      ) : artifact.available ? (
        <a className="icon-button" href={artifact.url}>
          <Download size={16} aria-hidden="true" />
          Download
        </a>
      ) : (
        <span className="pending-pill">Awaiting file</span>
      )}
      <DownloadFormatDetails artifact={artifact} />
    </article>
  );
}

function EmbeddingCommandPanel({ artifact }) {
  const [expanded, setExpanded] = useState(false);
  const metadata = artifact.metadata || {};
  const scriptUrl = absoluteUrl(artifact.url);
  const urlsUrl = absoluteUrl(metadata.urls_url);
  const apiBaseUrl = typeof window === "undefined" ? "/api" : `${window.location.origin}/api`;
  const localFolder = metadata.local_folder || `openkinetics_embeddings/${metadata.model_key || "model"}/residue_vecs`;
  const scriptName = artifact.relative_path?.split("/").pop() || `${metadata.model_key || "embeddings"}-download.sh`;
  const urlsName = metadata.urls_path?.split("/").pop() || `${metadata.model_key || "embeddings"}.urls.txt`;
  const scriptCommand = [
    `curl -fL --retry 5 --retry-all-errors --connect-timeout 10 --max-time 60 -o ${scriptName} "${scriptUrl}"`,
    `chmod +x ${scriptName}`,
    `OPENKINETICS_API_BASE_URL="${apiBaseUrl}" ./${scriptName}`
  ].join("\n");
  const ariaCommand = urlsUrl
    ? [
        `curl -fL --retry 5 --retry-all-errors --connect-timeout 10 --max-time 60 -o ${urlsName} "${urlsUrl}"`,
        `mkdir -p ${localFolder}`,
        `aria2c -c -x 4 -s 4 --max-tries=5 --retry-wait=5 --timeout=30 --lowest-speed-limit=1K --auto-file-renaming=false --allow-overwrite=true -d ${localFolder} -i ${urlsName}`
      ].join("\n")
    : "";

  if (!artifact.available) {
    return <span className="pending-pill">Awaiting commands</span>;
  }

  return (
    <div className="command-panel-shell">
      <button
        type="button"
        className="icon-button"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
        Download commands
      </button>
      {expanded ? (
        <div className="command-panel">
          <CommandBlock title="Curl script" command={scriptCommand} />
          {metadata.urls_available ? <CommandBlock title="Parallel download" command={ariaCommand} /> : null}
          {metadata.index_available ? (
            <p className="command-panel-note">
              Index: <a href={metadata.index_url}>{metadata.index_path}</a>
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function CommandBlock({ title, command }) {
  const [copied, setCopied] = useState(false);
  async function copyCommand() {
    if (!navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch (_error) {
      setCopied(false);
    }
  }

  return (
    <section className="command-block">
      <div className="command-block-header">
        <strong>{title}</strong>
        <button type="button" className="icon-button subtle" onClick={copyCommand}>
          <Copy size={15} aria-hidden="true" />
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre><code>{command}</code></pre>
    </section>
  );
}

function DownloadFormatDetails({ artifact }) {
  const details = artifact.metadata?.format_details || artifact.format_details;
  if (!details) return null;
  return (
    <details className="download-details">
      <summary>
        <FileText size={15} aria-hidden="true" />
        Format details
      </summary>
      <div className="download-details-body">
        {details.summary ? <p>{details.summary}</p> : null}
        {details.files?.length ? (
          <table className="format-table">
            <thead>
              <tr>
                <th>Path</th>
                <th>Format</th>
                <th>Contents</th>
              </tr>
            </thead>
            <tbody>
              {details.files.map((file) => (
                <tr key={`${artifact.artifact_key}-${file.path}`}>
                  <td><code>{file.path}</code></td>
                  <td>{file.format}</td>
                  <td>{file.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {details.fields?.length ? (
          <div className="field-list">
            <strong>Fields</strong>
            <div>
              {details.fields.map((field) => <code key={`${artifact.artifact_key}-${field}`}>{field}</code>)}
            </div>
          </div>
        ) : null}
        {details.notes?.length ? (
          <ul className="format-notes">
            {details.notes.map((note) => <li key={`${artifact.artifact_key}-${note}`}>{note}</li>)}
          </ul>
        ) : null}
      </div>
    </details>
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
        <div className="citation-subsection">
          <h3>Current Citation</h3>
          <p>
            Sajeevan et al., Robust Prediction of Enzyme Variant Kinetics with RealKcat,
            bioRxiv 2025. DOI: <a href={realKcatDoi}>{realKcatDoi}</a>
          </p>
          <CitationBox
            label="RealKcat BibTeX"
            citation={realKcatBibtex}
            filename="realkcat.bib"
          />
        </div>
      </section>
      <section className="panel wide-panel">
        <h2>OpenKinetics</h2>
        <p>
          Data curated by CatLog collaborators, served by{" "}
          <a href={openKineticsUrl}>OpenKinetics</a>.
        </p>
        <CitationBox
          label="OpenKinetics BibTeX"
          citation={openKineticsBibtex}
          filename="openkinetics.bib"
        />
      </section>
    </div>
  );
}

function CitationBox({ label, citation, filename }) {
  const [copied, setCopied] = useState(false);
  const downloadHref = useMemo(
    () => `data:text/x-bibtex;charset=utf-8,${encodeURIComponent(citation)}`,
    [citation]
  );

  async function copyCitation() {
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(citation);
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = citation;
        textArea.setAttribute("readonly", "");
        textArea.style.position = "fixed";
        textArea.style.opacity = "0";
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand("copy");
        document.body.removeChild(textArea);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch (_error) {
      setCopied(false);
    }
  }

  return (
    <div className="citation-box">
      <div className="citation-box-header">
        <strong>{label}</strong>
        <div className="citation-actions">
          <button type="button" className="icon-button subtle" onClick={copyCitation}>
            <Copy size={15} aria-hidden="true" />
            {copied ? "Copied" : "Copy"}
          </button>
          <a className="icon-button subtle" href={downloadHref} download={filename}>
            <Download size={15} aria-hidden="true" />
            Download .bib
          </a>
        </div>
      </div>
      <pre className="citation-code"><code>{citation}</code></pre>
    </div>
  );
}

const apiDocSections = [
  {
    title: "Release and Download Metadata",
    description: "Inspect the active release, release history, download files, command-panel metadata, and release-level counts.",
    endpoints: [
      {
        method: "GET",
        path: "/api/downloads/",
        purpose: "Grouped download artifacts for the latest release, including stats and embedding command metadata.",
        params: []
      },
      {
        method: "GET",
        path: "/api/releases/latest/",
        purpose: "Full manifest and schema for the latest release.",
        params: []
      },
      {
        method: "GET",
        path: "/api/releases/{release_id}/",
        purpose: "Manifest and schema for one immutable release.",
        params: [{ name: "release_id", values: "slug", description: "Release identifier such as openkinetics-catlog-full-2026-09." }]
      },
      {
        method: "GET",
        path: "/api/stats/",
        purpose: "Compact counts for the latest release.",
        params: []
      }
    ],
    examples: {
      curl: `curl -s https://data.openkinetics.org/api/downloads/ | jq '.release, .stats.counts'

curl -LO https://data.openkinetics.org/releases/openkinetics-catlog-full-2026-09/measurements.jsonl.gz

curl -s https://data.openkinetics.org/api/releases/latest/ | jq '.release.manifest.counts'`,
      python: `import requests

base = "https://data.openkinetics.org/api"

downloads = requests.get(f"{base}/downloads/", timeout=30).json()
print(downloads["release"]["release_id"])
print(downloads["stats"]["counts"])

latest = requests.get(f"{base}/releases/latest/", timeout=30).json()["release"]
print(latest["manifest"]["download_note"])`
    }
  },
  {
    title: "Measurement Search",
    description: "Page through kinetic measurements, use exact enzyme drilldown filters, and fetch rich measurement details by record key.",
    endpoints: [
      {
        method: "GET",
        path: "/api/measurements/",
        purpose: "Paginated measurement summaries for the latest release.",
        params: [
          { name: "q", values: "text", description: "Search over enzyme, substrate, EC, organism, IDs, source, and evidence fields." },
          { name: "page, page_size", values: "integers", description: "Pagination. page_size is capped at 100." },
          { name: "has_kcat, has_km, wild_type", values: "true or false", description: "Boolean filters for reported metrics and sequence type." },
          { name: "ec_number, ec_number_exact, ec_class", values: "text", description: "EC prefix, exact EC, or EC top-level class filtering." },
          { name: "organism, organism_exact, substrate", values: "text", description: "Organism and substrate text filters." },
          { name: "enzyme_identity", values: "true", description: "Use with enzyme_name, ec_number_exact, organism_exact, and optional uniprot for exact enzyme drilldown." }
        ]
      },
      {
        method: "GET",
        path: "/api/measurements/{record_key}/",
        purpose: "Full measurement detail including sequence, mutant fields, evidence, provenance, splits, and sequence artifacts.",
        params: [{ name: "record_key", values: "string", description: "Stable record identifier from measurement search results." }]
      },
      {
        method: "GET",
        path: "/api/facets/",
        purpose: "Filter facets for the latest release.",
        params: []
      }
    ],
    examples: {
      curl: `curl -sG https://data.openkinetics.org/api/measurements/ \\
  --data-urlencode 'q=ATP' \\
  --data-urlencode 'has_km=true' \\
  --data-urlencode 'page_size=10' | jq '.pagination, .results[0]'

curl -sG https://data.openkinetics.org/api/measurements/ \\
  --data-urlencode 'enzyme_identity=true' \\
  --data-urlencode 'enzyme_name=alcohol dehydrogenase' \\
  --data-urlencode 'ec_number_exact=1.1.1.1' \\
  --data-urlencode 'organism_exact=Homo sapiens' \\
  --data-urlencode 'page_size=100' | jq '.results[].record_key'

curl -s https://data.openkinetics.org/api/measurements/RECORD_KEY/ | jq '.measurement.sequence'`,
      python: `import requests

base = "https://data.openkinetics.org/api"

page = requests.get(
    f"{base}/measurements/",
    params={"q": "ATP", "has_km": "true", "page_size": 10},
    timeout=30,
).json()

record_key = page["results"][0]["record_key"]
detail = requests.get(f"{base}/measurements/{record_key}/", timeout=30).json()

sequence = detail["measurement"]["sequence"]
print(sequence["sequence_id"], sequence["is_mutant"], sequence["mutation_signature"])`
    }
  },
  {
    title: "Sequences, Substrates, and Artifacts",
    description: "Fetch sequence/substrate metadata, single-sequence ZIP artifacts, raw embedding arrays, and bulk embedding helper files.",
    endpoints: [
      {
        method: "GET",
        path: "/api/sequences/{sequence_id}/",
        purpose: "Full sequence metadata and amino-acid sequence.",
        params: [{ name: "sequence_id", values: "string", description: "Stable sequence ID from measurements or sequences.jsonl.gz." }]
      },
      {
        method: "GET",
        path: "/api/substrates/{substrate_id}/",
        purpose: "Substrate metadata including name, SMILES, and InChIKey when available.",
        params: [{ name: "substrate_id", values: "string", description: "Stable substrate ID from measurements or substrates.jsonl.gz." }]
      },
      {
        method: "GET",
        path: "/api/sequences/{sequence_id}/artifacts/{artifact_key}/",
        purpose: "Single-sequence ZIP artifact with metadata plus one array.",
        params: [{ name: "artifact_key", values: "esm2_residue, esmc_residue, prot_t5_residue, pseq2sites_scores", description: "Artifact to package for one sequence." }]
      },
      {
        method: "GET",
        path: "/api/artifacts/{artifact_key}/{sequence_id}.npy",
        purpose: "Raw embedding .npy stream for bulk command downloads.",
        params: [{ name: "artifact_key", values: "esm2_residue, esmc_residue, prot_t5_residue", description: "Embeddings only. Binding-site scores use the normal download bundle or single-sequence ZIP endpoint." }]
      }
    ],
    examples: {
      curl: `curl -s https://data.openkinetics.org/api/sequences/SEQUENCE_ID/ | jq '.sequence.length'

curl -L -o SEQUENCE_ID_esm2_residue.zip \\
  https://data.openkinetics.org/api/sequences/SEQUENCE_ID/artifacts/esm2_residue/

curl -L -C - -o openkinetics_embeddings/esm2/residue_vecs/SEQUENCE_ID.npy \\
  https://data.openkinetics.org/api/artifacts/esm2_residue/SEQUENCE_ID.npy

curl -L -o openkinetics-catlog-full-2026-09-esm2-download.sh \\
  https://data.openkinetics.org/releases/openkinetics-catlog-full-2026-09/downloads/openkinetics-catlog-full-2026-09-esm2-download.sh`,
      python: `from pathlib import Path
import requests

base = "https://data.openkinetics.org/api"
sequence_id = "SEQUENCE_ID"

sequence = requests.get(f"{base}/sequences/{sequence_id}/", timeout=30).json()["sequence"]
print(sequence["length"], sequence["primary_uniprot_id"])

out = Path("openkinetics_embeddings/esm2/residue_vecs")
out.mkdir(parents=True, exist_ok=True)
url = f"{base}/artifacts/esm2_residue/{sequence_id}.npy"
with requests.get(url, stream=True, timeout=120) as response:
    response.raise_for_status()
    with open(out / f"{sequence_id}.npy", "wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                handle.write(chunk)`
    }
  }
];

function ExampleTabs({ examples }) {
  const tabs = Object.keys(examples);
  const [active, setActive] = useState(tabs[0]);
  return (
    <div className="api-example-tabs">
      <div className="api-tab-list" role="tablist" aria-label="Example language">
        {tabs.map((tab) => (
          <button
            type="button"
            role="tab"
            aria-selected={active === tab}
            className={active === tab ? "active" : ""}
            onClick={() => setActive(tab)}
            key={tab}
          >
            {tab}
          </button>
        ))}
      </div>
      <pre className="code-block api-code"><code>{examples[active]}</code></pre>
    </div>
  );
}

function EndpointTable({ endpoints }) {
  return (
    <div className="api-endpoint-list">
      {endpoints.map((endpoint) => (
        <article className="api-endpoint" key={`${endpoint.method}-${endpoint.path}`}>
          <div className="api-endpoint-heading">
            <span className="method-pill">{endpoint.method}</span>
            <code>{endpoint.path}</code>
          </div>
          <p>{endpoint.purpose}</p>
          {endpoint.params.length ? (
            <table className="api-param-table">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Values</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {endpoint.params.map((param) => (
                  <tr key={`${endpoint.path}-${param.name}`}>
                    <td><code>{param.name}</code></td>
                    <td>{param.values}</td>
                    <td>{param.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function ApiDocsPage() {
  return (
    <div className="page text-page">
      <div className="page-heading">
        <h1>API</h1>
        <p>JSON endpoints for releases, measurements, sequence metadata, download files, and sequence artifacts.</p>
      </div>
      <section className="api-overview-grid">
        <div>
          <span>Base URL</span>
          <code>https://data.openkinetics.org/api</code>
        </div>
        <div>
          <span>Response format</span>
          <strong>JSON</strong>
        </div>
        <div>
          <span>Pagination</span>
          <strong>page + page_size</strong>
        </div>
      </section>
      {apiDocSections.map((section) => (
        <section className="panel wide-panel api-doc-section" key={section.title}>
          <h2>{section.title}</h2>
          <p>{section.description}</p>
          <EndpointTable endpoints={section.endpoints} />
          <ExampleTabs examples={section.examples} />
        </section>
      ))}
    </div>
  );
}

export default function App() {
  return <Layout />;
}
