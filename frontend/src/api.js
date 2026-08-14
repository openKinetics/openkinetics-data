import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

const client = axios.create({
  baseURL: API_BASE,
  timeout: 20000
});

export async function fetchStats() {
  const { data } = await client.get("/stats/");
  return data;
}

export async function fetchFacets() {
  const { data } = await client.get("/facets/");
  return data;
}

export async function fetchMeasurements(params) {
  const { data } = await client.get("/measurements/", { params });
  return data;
}

export async function fetchMeasurement(recordKey) {
  const { data } = await client.get(`/measurements/${recordKey}/`);
  return data.measurement;
}

export async function fetchDownloads() {
  const { data } = await client.get("/downloads/");
  return data;
}

export async function fetchReleases() {
  const { data } = await client.get("/releases/");
  return data.releases;
}

export async function fetchLatestRelease() {
  const { data } = await client.get("/releases/latest/");
  return data.release;
}

