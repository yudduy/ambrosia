import { useEffect, useState, type ComponentType } from "react";
import { Activity, Asleep, Chat, Home, Moon, Restaurant, Sun, UserAvatar } from "@carbon/icons-react";
import { NavLink, Route, Routes } from "react-router-dom";
import { AskDrawer } from "./components/AskDrawer";
import { ProfilePanel } from "./components/ProfilePanel";
import { HomePage } from "./pages/HomePage";
import { DomainPage } from "./pages/DomainPage";
import { NutritionPage } from "./pages/NutritionPage";

const navigation: Array<[string, string, ComponentType<{ size?: number }>]> = [
  ["Home", "/", Home],
  ["Fitness", "/fitness", Activity],
  ["Sleep", "/sleep", Asleep],
  ["Nutrition", "/nutrition", Restaurant],
];

export function App() {
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [dark, setDark] = useState(() => localStorage.getItem("ambrosia-theme") === "dark" || (!localStorage.getItem("ambrosia-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches));
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    localStorage.setItem("ambrosia-theme", dark ? "dark" : "light");
  }, [dark]);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand__mark">A</span><strong>Ambrosia</strong></div>
        <nav aria-label="Primary navigation">
          {navigation.map(([label, path, Icon]) => (
            <NavLink key={path} to={path} end={path === "/"} className={({ isActive }) => isActive ? "active" : ""}>
              <Icon size={19} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar__bottom">
          <button onClick={() => setProfileOpen(true)}><UserAvatar size={20} /><span>Profile</span></button>
          <button onClick={() => setDark((value) => !value)} aria-label={dark ? "Use light mode" : "Use dark mode"}>{dark ? <Sun size={20} /> : <Moon size={20} />}<span>{dark ? "Light" : "Dark"}</span></button>
        </div>
      </aside>
      <header className="mobile-header"><div className="brand"><span className="brand__mark">A</span><strong>Ambrosia</strong></div><div><button className="icon-button" onClick={() => setDark((value) => !value)} aria-label="Toggle color theme">{dark ? <Sun size={20} /> : <Moon size={20} />}</button><button className="icon-button" onClick={() => setProfileOpen(true)} aria-label="Open profile"><UserAvatar size={20} /></button></div></header>
      <main id="main-content">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/fitness" element={<DomainPage domain="fitness" />} />
          <Route path="/sleep" element={<DomainPage domain="sleep" />} />
          <Route path="/nutrition" element={<NutritionPage />} />
        </Routes>
      </main>
      <button className="ask-fab" aria-label="Ask Ambrosia" onClick={() => setAssistantOpen(true)}><Chat size={20} /><span>Ask</span></button>
      <nav className="bottom-nav" aria-label="Primary navigation">
        {navigation.map(([label, path, Icon]) => <NavLink key={path} to={path} end={path === "/"}><Icon size={20} /><span>{label}</span></NavLink>)}
      </nav>
      {(assistantOpen || profileOpen) && <button className="scrim" aria-label="Close panel" onClick={() => { setAssistantOpen(false); setProfileOpen(false); }} />}
      <AskDrawer open={assistantOpen} onClose={() => setAssistantOpen(false)} />
      <ProfilePanel open={profileOpen} onClose={() => setProfileOpen(false)} />
    </div>
  );
}
