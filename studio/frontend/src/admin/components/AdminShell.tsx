import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { apiPost } from "../../lib/api";

function NavItem({ to, end, children }: { to: string; end?: boolean; children: ReactNode }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
      {children}
    </NavLink>
  );
}

export function AdminShell({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  async function onLogout() {
    await apiPost("/api/admin/logout");
    window.location.reload();
  }

  return (
    <div className="app-shell">
      <button type="button" className="mobile-menu-btn" aria-label="Open menu" onClick={() => setMobileOpen(true)}>
        &#9776;
      </button>
      {mobileOpen && <div className="sidebar-overlay is-open" onClick={() => setMobileOpen(false)} />}
      <aside className={`app-sidebar ${mobileOpen ? "is-open" : ""}`} onClick={() => setMobileOpen(false)}>
        <NavLink to="/" end className="app-sidebar-brand">
          <span className="dot" />
          <span>MIVAIS Studio</span>
        </NavLink>

        <div className="nav-section">Research</div>
        <NavItem to="/" end>
          Studies
        </NavItem>
        <NavItem to="/studies/new">Register a study</NavItem>
        <NavItem to="/library">Library</NavItem>

        <div className="nav-section">Live</div>
        <NavItem to="/sessions">Sessions</NavItem>

        <div className="nav-section">Analytics</div>
        <NavItem to="/compare">Compare studies</NavItem>
        <NavItem to="/irr">IRR (κ)</NavItem>

        <div className="nav-section">System</div>
        <NavItem to="/webhooks">Webhooks</NavItem>
        <NavItem to="/api-access">API access</NavItem>
        <NavItem to="/users">Admin users</NavItem>
        <NavItem to="/audit">Audit log</NavItem>
        <a className="nav-item" href="/health" target="_blank" rel="noopener noreferrer">
          Health
        </a>

        <div style={{ flex: 1 }} />

        <button
          type="button"
          className="nav-item"
          style={{ border: 0, background: "transparent", textAlign: "left", cursor: "pointer", font: "inherit", width: "100%" }}
          onClick={onLogout}
        >
          Log out
        </button>
      </aside>

      <main className="app-main">{children}</main>
    </div>
  );
}
