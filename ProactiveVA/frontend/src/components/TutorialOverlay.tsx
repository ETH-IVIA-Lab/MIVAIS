export function TutorialOverlay({ onClose }: { onClose: () => void }) {
  return (
    <div id="tutorial-host">
      <div id="tutorial">
        <h2>Welcome — what you're doing here</h2>
        <p>
          You are an analyst for the city of Abila. On the evening of <b>2014-01-23</b>, the POK
          (Protectors of Kronos) held a rally that escalated into several public-safety incidents —
          fires, shootings, hostage situations, traffic accidents. You have ~4&nbsp;000 microblogs and
          call-center records covering 17:00–21:30.
        </p>
        <p>
          <span className="step-h">Goal:</span> identify as many distinct events as you can. For each
          one, record <b>time, location, and people involved</b> as a Note in the right panel.
        </p>

        <p>
          <span className="step-h">Suggested workflow</span>
        </p>
        <ul>
          <li>
            Drag-select a time range on the <b>Timeline</b> (top-right) to focus on one peak.
          </li>
          <li>
            Click an orange hexagon on the <b>Map</b> (top-left) to see messages from that area.
          </li>
          <li>
            Skim the <b>Messages</b> list (bottom-left); add a keyword like <code>fire</code> to narrow it.
          </li>
          <li>
            Click an entity node in the <b>Entity Graph</b> (bottom-right) to pivot.
          </li>
          <li>
            When you've identified an event, write a <b>Note</b> (right panel). The assistant will
            cross-check it.
          </li>
        </ul>

        <p>
          <span className="step-h">The proactive assistant</span> watches what you do and helps in
          three ways:
        </p>
        <ul>
          <li>
            <b>Suggestions</b> appear as yellow cards in the chat. Click <b>Try it</b> and the
            assistant will carry it out — you'll see its reasoning live.
          </li>
          <li>
            <b>Verification</b>: every note you write is cross-checked against the data; you'll get a
            warning if something looks off.
          </li>
          <li>
            <b>Direct chat</b>: type <code>@assistant …</code> in the chat input to ask it directly
            (e.g. <i>"@assistant filter to fire-related messages"</i>).
          </li>
        </ul>

        <p>
          You can disable any of the three help categories in the top bar, or move the{" "}
          <b>Help interval</b> slider — higher = the assistant waits longer before chiming in.
        </p>

        <div className="actions">
          <button className="primary" onClick={onClose}>
            Got it — start investigating
          </button>
        </div>
      </div>
    </div>
  );
}
