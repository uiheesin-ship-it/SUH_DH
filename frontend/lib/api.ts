// Typed fetch wrapper: validates every response with Zod before it reaches the UI.
// Generic over the schema so the return type is exactly the schema's *output*
// type (fields with .default([]) are non-optional there).
import { z } from "zod";

async function get<S extends z.ZodTypeAny>(path: string, schema: S): Promise<z.output<S>> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return schema.parse(await res.json());
}

async function post<S extends z.ZodTypeAny>(path: string, schema: S): Promise<z.output<S>> {
  const res = await fetch(path, { method: "POST" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return schema.parse(await res.json());
}

export const api = { get, post };
