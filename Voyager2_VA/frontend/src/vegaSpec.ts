import type { ViewSpec } from "./types";

function processEnc(enc?: { field?: string; type?: string; aggregate?: string; bin?: boolean; timeUnit?: string }) {
  if (!enc || !enc.field) return null;
  if (enc.field === "*") return { aggregate: "count", type: "quantitative" };
  const e: Record<string, unknown> = { field: enc.field, type: enc.type || "nominal" };
  if (enc.aggregate && enc.aggregate !== "none") e.aggregate = enc.aggregate;
  if (enc.bin) e.bin = true;
  if (enc.timeUnit) e.timeUnit = enc.timeUnit;
  return e;
}


export interface ChartFilter {
  field: string;
  type: "quantitative" | "nominal";
  min?: number;
  max?: number;
  values?: string[];
  valid?: boolean;
}

function filterPredicates(filters: ChartFilter[]): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  for (const f of filters) {
    if (f.valid) {
      out.push({ filter: { field: f.field, valid: true } });
    } else if (f.type === "quantitative") {
      out.push({ filter: { field: f.field, range: [f.min ?? null, f.max ?? null] } });
    } else if (f.values && f.values.length) {
      out.push({ filter: { field: f.field, oneOf: f.values } });
    }
  }
  return out;
}

export function buildVegaLiteSpec(
  viewSpec: ViewSpec | null | undefined,
  dataset: unknown[],
  w?: number,
  h?: number,
  compact = false,
  filters: ChartFilter[] = [],
) {
  if (!viewSpec) return null;
  const vl: Record<string, unknown> = { $schema: "https://vega.github.io/schema/vega-lite/v5.json" };
  vl.data = { values: dataset };
  const transform = filterPredicates(filters);
  if (transform.length) vl.transform = transform;

  vl.mark = viewSpec.mark && viewSpec.mark !== "auto" ? viewSpec.mark : "point";

  const encoding: Record<string, unknown> = {};
  if (viewSpec.encoding) {
    for (const [ch, enc] of Object.entries(viewSpec.encoding)) {
      const processed = processEnc(enc);
      if (processed) encoding[ch] = processed;
    }
  } else if (viewSpec.encodings) {
    viewSpec.encodings.forEach((enc) => {
      if (!enc.channel) return;
      const processed = processEnc(enc);
      if (processed) encoding[enc.channel] = processed;
    });
  }
  vl.encoding = encoding;

  const faceted = "row" in encoding || "column" in encoding;
  if (w) vl.width = w;
  if (h) vl.height = h;
  if (w && !faceted) vl.autosize = { type: "fit", contains: "padding" };

  if (viewSpec._title && !compact) vl.title = viewSpec._title;
  if (compact) {
    vl.config = {
      axis: { labelLimit: 80, labelFontSize: 9, titleFontSize: 10 },
      legend: { labelLimit: 80, labelFontSize: 9, titleFontSize: 10, symbolSize: 50 },
    };
  }

  return vl;
}
