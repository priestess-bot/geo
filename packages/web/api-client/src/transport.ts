import type { ProblemDetails } from "@geo/types/common";

export class GeoApiError extends Error {
  constructor(readonly problem: ProblemDetails) {
    super(problem.detail ?? problem.title);
  }
}

export async function requestJson<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(new URL(path, baseUrl), init);
  if (!response.ok) {
    throw new GeoApiError((await response.json()) as ProblemDetails);
  }
  return (await response.json()) as T;
}
