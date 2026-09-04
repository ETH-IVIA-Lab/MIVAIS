import { useEffect, useRef } from "react";
import L from "leaflet";
import { useProactive } from "../context";
import { filteredMessages, hexStats } from "../helpers";
import type { Hex, StaticData } from "../types";


const POIS = [
  { name: "Abila City Park", lat: 36.059, lon: 24.875 },
  { name: "Dancing Dolphin (Fire)", lat: 36.057, lon: 24.892 },
  { name: "Gelato Galore (Standoff)", lat: 36.054, lon: 24.902 },
  { name: "Schaber Ave (Hit & Run)", lat: 36.054, lon: 24.857 },
];

export function MapView({ staticData }: { staticData: StaticData }) {
  const { worldState, sendAction } = useProactive();
  const hostRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const hexLayer = useRef<L.LayerGroup | null>(null);
  const annoLayer = useRef<L.LayerGroup | null>(null);
  const ccLayer = useRef<L.LayerGroup | null>(null);
  const mbLayer = useRef<L.LayerGroup | null>(null);
  const headRef = useRef<HTMLElement>(null);

  // ── One-time map init ──────────────────────────────────────────────────────
  useEffect(() => {
    const host = hostRef.current;
    if (!host || mapRef.current) return;

    const hexes = staticData.hexgrid;
    const map = L.map(host, { zoomControl: true, attributionControl: false });
    if (hexes.length) {
      const lats = hexes.flatMap((h) => h.polygon.map((p) => p[1]));
      const lons = hexes.flatMap((h) => h.polygon.map((p) => p[0]));
      map.fitBounds([
        [Math.min(...lats), Math.min(...lons)],
        [Math.max(...lats), Math.max(...lons)],
      ]);
    } else {
      map.setView([36.055, 24.875], 14);
    }

    host.style.background = "#f1f5f9";
    if (staticData.streets.features) {
      L.geoJSON(staticData.streets, {
        style: { color: "#475569", weight: 1.1, opacity: 0.85 },
        onEachFeature: (feature, layer) => {
          const name = feature.properties?.name || "";
          if (name) layer.bindTooltip(name, { sticky: true, direction: "top", className: "street-tt" });
        },
      }).addTo(map);
    }

    const Label = L.Control.extend({
      onAdd: () => {
        const div = L.DomUtil.create("div", "city-label");
        div.innerHTML = 'Abila <span style="font-weight:400;color:#94a3b8">· Kronos</span>';
        return div;
      },
    });
    new Label({ position: "topright" }).addTo(map);

    hexLayer.current = L.layerGroup().addTo(map);
    annoLayer.current = L.layerGroup().addTo(map);
    ccLayer.current = L.layerGroup().addTo(map);
    mbLayer.current = L.layerGroup().addTo(map);

    for (const p of POIS) {
      L.marker([p.lat, p.lon], {
        icon: L.divIcon({
          className: "",
          html: `<div class="poi-marker"></div><div class="poi-label">${p.name}</div>`,
          iconSize: undefined,
          iconAnchor: [5, 5],
        }),
        interactive: false,
        keyboard: false,
        zIndexOffset: -100,
      }).addTo(map);
    }

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [staticData]);

  const openMapNotePopup = (h: Hex) => {
    const map = mapRef.current;
    if (!map) return;
    const c = h.center; // [lon, lat]
    const popup = L.popup({ className: "map-note", closeButton: true, autoClose: true })
      .setLatLng([c[1], c[0]])
      .setContent(
        `<div class="map-note-form">
           <div class="head">Add note for ${h.id}</div>
           <input class="mn-title" placeholder="Title (e.g. Fire incident)">
           <input class="mn-label" placeholder="Label (e.g. ~18:42, fire crew dispatched)">
           <button class="mn-submit">Submit</button>
         </div>`,
      )
      .openOn(map);
    setTimeout(() => {
      const root = popup.getElement();
      if (!root) return;
      const titleEl = root.querySelector<HTMLInputElement>(".mn-title");
      const labelEl = root.querySelector<HTMLInputElement>(".mn-label");
      const btn = root.querySelector<HTMLButtonElement>(".mn-submit");
      titleEl?.focus();
      if (btn)
        btn.onclick = () => {
          const title = titleEl?.value.trim() || "";
          const label = labelEl?.value.trim() || "";
          if (!title && !label) {
            titleEl?.focus();
            return;
          }
          const ids = staticData.dataset
            .filter((m) => m.hex_id === h.id)
            .slice(0, 20)
            .map((m) => m.id);
          sendAction({ action: "add_note", title, label, view: `Map · ${h.id}`, hex_id: h.id, evidence: ids });
          map.closePopup(popup);
        };
    }, 0);
  };

  // ── Hexes + note annotations (redrawn on filter/selection/notes change) ────
  useEffect(() => {
    const layer = hexLayer.current;
    const anno = annoLayer.current;
    if (!layer || !anno) return;
    layer.clearLayers();
    anno.clearLayers();

    const msgs = filteredMessages(staticData.dataset, worldState, "hex");
    const stats = hexStats(msgs);
    const maxRisk = Math.max(1, ...Object.values(stats).map((s) => s.risk));

    if (headRef.current) {
      const total = staticData.dataset.length;
      const geo = staticData.dataset.reduce((n, m) => n + (m.lat != null ? 1 : 0), 0);
      headRef.current.textContent = `Map — Abila & hexgrid (${geo} geotagged of ${total} messages)`;
    }

    const centresById = new Map(staticData.hexgrid.map((h) => [h.id, h.center]));

    for (const h of staticData.hexgrid) {
      const s = stats[h.id];
      const isSelected = worldState.selected_hex === h.id;
      if (!s && !isSelected) continue;
      const ll = h.polygon.map((p) => [p[1], p[0]]) as [number, number][];
      const intensity = s ? Math.sqrt(s.risk / maxRisk) : 0;
      const r = Math.round(245 - 65 * intensity);
      const g = Math.round(158 - 158 * intensity);
      const b = Math.round(11 - 11 * intensity);
      const fill = isSelected ? "rgba(220,38,38,0.65)" : `rgba(${r},${g},${b},${0.22 + 0.55 * intensity})`;
      const poly = L.polygon(ll, {
        color: isSelected ? "#b91c1c" : "#d97706",
        weight: isSelected ? 2.5 : 0.6,
        fillColor: fill,
        fillOpacity: 1,
      });
      poly.on("click", () => sendAction({ action: "select_hexagon", hex_id: h.id }));
      poly.on("dblclick", (ev) => {
        L.DomEvent.stop(ev);
        openMapNotePopup(h);
      });
      if (s) {
        poly.bindTooltip(
          `<b>${h.id}</b><br>Risk level: ${s.risk.toFixed(2)}<br>Influence rate: ${(s.influence * 100).toFixed(2)}%` +
            `<br>${s.mb} microblog · ${s.cc} call-center<br>${s.neg} neg · ${s.pos} pos · ${s.neu} neu` +
            `<br><small>double-click to add note</small>`,
          { sticky: true },
        );
      } else {
        poly.bindTooltip(`${h.id} · empty (selected) · double-click to add note`, { sticky: true });
      }
      poly.addTo(layer);
    }

    for (const note of worldState.notes || []) {
      if (!note.hex_id) continue;
      const c = centresById.get(note.hex_id);
      if (!c) continue;
      L.marker([c[1], c[0]], {
        icon: L.divIcon({
          className: "",
          html: `<div class="map-anno">${(note.title || "").slice(0, 40).replace(/</g, "&lt;")}</div>`,
          iconSize: undefined,
          iconAnchor: [0, 0],
        }),
        interactive: false,
        keyboard: false,
      }).addTo(anno);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    staticData,
    worldState.selected_hex,
    worldState.selected_entity,
    worldState.time_range,
    worldState.keyword_filter,
    worldState.notes,
  ]);

  // ── Point markers ───────────────────────────────────────────────────────────
  useEffect(() => {
    const cc = ccLayer.current;
    const mb = mbLayer.current;
    if (!cc || !mb) return;
    cc.clearLayers();
    mb.clearLayers();
    let nCc = 0;
    let nMb = 0;
    for (const m of filteredMessages(staticData.dataset, worldState, "hex")) {
      if (m.lat == null || m.lon == null) continue;
      if (m.type === "ccdata") {
        if (nCc++ > 200) continue;
        L.circleMarker([m.lat, m.lon], { radius: 4, color: "#dc2626", weight: 1, fillOpacity: 0.85 })
          .bindTooltip(`<b>${(m.timestamp || "").slice(11, 19)}</b> ${(m.message || "").replace(/</g, "&lt;")}<br>${m.location || ""}`)
          .addTo(cc);
      } else if (m.type === "mbdata") {
        if (nMb++ > 300) continue;
        L.circleMarker([m.lat, m.lon], { radius: 2, color: "#1d4ed8", fillOpacity: 0.5, weight: 0 }).addTo(mb);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [staticData, worldState.selected_entity, worldState.time_range, worldState.keyword_filter]);

  return (
    <>
      <header className="subhead" ref={headRef}>
        Map — Abila &amp; hexgrid
      </header>
      <div className="body">
        <div id="map" ref={hostRef} />
      </div>
    </>
  );
}
