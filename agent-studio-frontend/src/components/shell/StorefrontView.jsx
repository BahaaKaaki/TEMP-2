/**
 * StorefrontView — marketplace landing page.
 *
 * Single-column layout: search, featured spotlight (up to 3 tools), then
 * section grids (Apex OS Agents, Strategy& Tools). Cards use marketplace
 * and shared-tools APIs; Chat starts a new session and opens chat view.
 */

import { useEffect, useMemo, useState } from "react";
import { useWorkflow } from "../../context/WorkflowContext";
import { fetchMarketplaceWorkflows } from "../../api/marketplace";
import { fetchVisibleSharedTools } from "../../api/shared-tools";
import { createChatSession, API_BASE_URL } from "../../api/client";
import { safeError } from "../../utils/safeLogger";
import { useFigmaPx } from "../builder/useFigmaScale";
import {
  COLOR,
  FONT,
  SEARCH,
  APP_CARD,
  SPOTLIGHT,
  LAYOUT,
  colorForName,
  initialsForName,
} from "./apexShellSpec";
import { ApexStorefrontLoading, ApexShellEmpty } from "./ApexShellStates";
import AppIcon from "../ui/AppIcon";
import SubmitToolDialog from "./SubmitToolDialog";

const CARD_TILT_TRANSLATE = 8;
const CARD_TILT_ROTATE = 4.5;
const CARD_TILT_LIFT = -2;

function applyStorefrontCardTilt(el, clientX, clientY) {
  if (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ) {
    return;
  }
  const rect = el.getBoundingClientRect();
  const x = (clientX - rect.left) / rect.width - 0.5;
  const y = (clientY - rect.top) / rect.height - 0.5;
  const tx = x * CARD_TILT_TRANSLATE * 2;
  const ty = y * CARD_TILT_TRANSLATE * 2 + CARD_TILT_LIFT;
  const ry = x * CARD_TILT_ROTATE * 2;
  const rx = -y * CARD_TILT_ROTATE * 2;
  el.style.transform = `translate3d(${tx}px, ${ty}px, 0) rotateX(${rx}deg) rotateY(${ry}deg)`;
}

function resetStorefrontCardTilt(el) {
  el.style.transition =
    "transform 450ms cubic-bezier(0.32, 0.72, 0, 1), border-color 220ms ease, box-shadow 220ms ease";
  el.style.transform = "";
  const clearTransition = () => {
    el.style.transition = "border-color 220ms ease, box-shadow 220ms ease";
    el.removeEventListener("transitionend", clearTransition);
  };
  el.addEventListener("transitionend", clearTransition);
}

// External apps load dynamically via fetchVisibleSharedTools() (see seed_shared_tools_external_apps.sql).

const SPOTLIGHT_MAX = 3;

function buildSpotlightItems(filteredAgents, sharedApps) {
  const items = [];
  for (const tool of filteredAgents) {
    if (items.length >= SPOTLIGHT_MAX) break;
    items.push({ kind: "agent", id: tool.id, data: tool });
  }
  for (const app of sharedApps) {
    if (items.length >= SPOTLIGHT_MAX) break;
    items.push({ kind: "external", id: app.id, data: app });
  }
  return items;
}

// ────── Shared card chrome ───────────────────────────────────────────────
function StorefrontCardShell({
  hover,
  onEnter,
  onLeave,
  children,
  spotlight = false,
}) {
  const { px } = useFigmaPx();
  const spec = spotlight ? SPOTLIGHT : APP_CARD;

  const handleEnter = (e) => {
    e.currentTarget.style.transition =
      "border-color 220ms ease, box-shadow 220ms ease";
    onEnter();
    applyStorefrontCardTilt(e.currentTarget, e.clientX, e.clientY);
  };

  const handleMove = (e) => {
    applyStorefrontCardTilt(e.currentTarget, e.clientX, e.clientY);
  };

  const handleLeave = (e) => {
    resetStorefrontCardTilt(e.currentTarget);
    onLeave();
  };

  return (
    <div
      className={`storefront-card${spotlight ? " storefront-card--spotlight" : ""}${hover ? " storefront-card--hover" : ""}`}
      style={{
        minHeight: px(spec.height),
        fontFamily: FONT.family,
        gap: px(spec.gap),
        padding: px(spec.padding),
        borderRadius: px(spec.radius),
      }}
      onMouseEnter={handleEnter}
      onMouseMove={handleMove}
      onMouseLeave={handleLeave}
    >
      {children}
    </div>
  );
}

function StorefrontCardIcon({ glowColor, children, spotlight = false }) {
  const { px } = useFigmaPx();
  const spec = spotlight ? SPOTLIGHT : APP_CARD;
  return (
    <div
      className="storefront-card-icon-wrap"
      style={{
        "--storefront-icon-glow": glowColor,
        width: px(spec.iconSize),
        height: px(spec.iconSize),
      }}
    >
      {children}
    </div>
  );
}

function storefrontPillStyle(pxFn) {
  return {
    fontFamily: FONT.family,
    height: pxFn(APP_CARD.pill.height),
    paddingLeft: pxFn(APP_CARD.pill.paddingX),
    paddingRight: pxFn(APP_CARD.pill.paddingX),
    borderRadius: pxFn(APP_CARD.pill.radius),
    fontSize: pxFn(FONT.pillButton.size),
    lineHeight: `${pxFn(FONT.pillButton.height)}px`,
    fontWeight: FONT.pillButton.weight,
  };
}

function StorefrontCardCopy({ title, description, cta, px: pxFn }) {
  const textTitle = {
    fontFamily: FONT.family,
    fontSize: pxFn(FONT.body1Bold.size),
    lineHeight: `${pxFn(FONT.body1Bold.height)}px`,
  };
  const textDesc = {
    fontFamily: FONT.family,
    fontSize: pxFn(FONT.body2.size),
    lineHeight: `${pxFn(FONT.body2.height)}px`,
  };
  return (
    <div className="storefront-card-body">
      <p className="storefront-card-title" style={textTitle} title={title}>
        {title}
      </p>
      <p className="storefront-card-desc" style={textDesc} title={description}>
        {description || "—"}
      </p>
      <div className="storefront-card-cta-row">{cta}</div>
    </div>
  );
}

function SectionHeader({ title, count }) {
  const { px } = useFigmaPx();
  return (
    <div className="storefront-section-header">
      <h2
        className="storefront-section-title"
        style={{
          fontFamily: FONT.family,
          fontSize: px(FONT.sub2Bold.size),
          lineHeight: `${px(FONT.sub2Bold.height)}px`,
        }}
      >
        {title}
      </h2>
      <span
        className="storefront-section-badge"
        style={{ fontFamily: FONT.family }}
      >
        {count}
      </span>
    </div>
  );
}

function ToolCard({ tool, onAction, busy, spotlight = false }) {
  const { px } = useFigmaPx();
  const [hover, setHover] = useState(false);
  const cardSpec = spotlight ? SPOTLIGHT : APP_CARD;

  const title = tool.marketplaceName || tool.name || "Untitled tool";
  const description = tool.marketplaceDescription || tool.description || "";
  const iconColor = colorForName(title);
  const iconText = initialsForName(title);
  const hasIcon = tool.icon && tool.icon.startsWith("/");

  return (
    <StorefrontCardShell
      spotlight={spotlight}
      hover={hover}
      onEnter={() => setHover(true)}
      onLeave={() => setHover(false)}
    >
      <StorefrontCardIcon glowColor={iconColor} spotlight={spotlight}>
        {hasIcon ? (
          <img
            src={`${API_BASE_URL}${tool.icon}`}
            alt=""
            className="storefront-card-icon"
            style={{ borderRadius: px(cardSpec.iconRadius) }}
          />
        ) : (
          <div
            className="storefront-card-icon storefront-card-icon--tile"
            style={{
              borderRadius: px(cardSpec.iconRadius),
              backgroundColor: iconColor,
              fontSize: px(spotlight ? cardSpec.iconInitialsSize : 28),
            }}
          >
            {iconText}
          </div>
        )}
      </StorefrontCardIcon>

      <StorefrontCardCopy
        title={title}
        description={description}
        px={px}
        cta={
          <button
            type="button"
            className="storefront-cta storefront-cta--chat"
            style={storefrontPillStyle(px)}
            disabled={busy}
            onClick={() => onAction(tool)}
          >
            {busy ? "…" : "Chat"}
          </button>
        }
      />
    </StorefrontCardShell>
  );
}

function ExternalAppCard({ app, spotlight = false }) {
  const { px } = useFigmaPx();
  const [hover, setHover] = useState(false);
  const cardSpec = spotlight ? SPOTLIGHT : APP_CARD;
  const iconColor = colorForName(app.name);
  const iconText = initialsForName(app.name);

  return (
    <StorefrontCardShell
      spotlight={spotlight}
      hover={hover}
      onEnter={() => setHover(true)}
      onLeave={() => setHover(false)}
    >
      <StorefrontCardIcon glowColor={iconColor} spotlight={spotlight}>
        {app.icon ? (
          <img
            src={app.icon}
            alt=""
            className="storefront-card-icon"
            style={{ borderRadius: px(cardSpec.iconRadius) }}
          />
        ) : (
          <span
            className="flex items-center justify-center w-full h-full"
            style={{
              backgroundColor: iconColor,
              color: COLOR.white,
              fontFamily: FONT.family,
              fontSize: px(spotlight ? cardSpec.iconInitialsSize : 28),
              fontWeight: 700,
              letterSpacing: 0.5,
              borderRadius: px(cardSpec.iconRadius),
            }}
          >
            {iconText}
          </span>
        )}
      </StorefrontCardIcon>

      <StorefrontCardCopy
        title={app.name}
        description={app.description}
        px={px}
        cta={
          <a
            href={app.link}
            target="_blank"
            rel="noopener noreferrer"
            className="storefront-cta storefront-cta--launch"
            style={storefrontPillStyle(px)}
          >
            Launch
          </a>
        }
      />
    </StorefrontCardShell>
  );
}

function StorefrontSpotlight({ items, busyId, onStart }) {
  if (items.length === 0) return null;

  return (
    <div
      className={`storefront-spotlight storefront-spotlight--count-${items.length}`}
      aria-label="Featured tools"
    >
      {items.map((item) =>
        item.kind === "agent" ? (
          <ToolCard
            key={`agent-${item.id}`}
            tool={item.data}
            busy={busyId === item.id}
            onAction={onStart}
            spotlight
          />
        ) : (
          <ExternalAppCard
            key={`external-${item.id}`}
            app={item.data}
            spotlight
          />
        ),
      )}
    </div>
  );
}

function SearchInput({ value, onChange, placeholder, width = "100%" }) {
  const { px } = useFigmaPx();
  const [focused, setFocused] = useState(false);
  return (
    <div
      className="kb-inline-search flex items-center"
      style={{
        width,
        height: px(SEARCH.height),
        borderRadius: px(SEARCH.radius),
        paddingLeft: px(SEARCH.paddingX),
        paddingRight: px(SEARCH.paddingX),
        gap: px(SEARCH.gap),
        backgroundColor: SEARCH.bg,
        border: `1px solid ${focused ? COLOR.rose : SEARCH.border}`,
        transition: "border-color 150ms",
      }}
    >
      <AppIcon
        name="search"
        size={px(SEARCH.iconSize)}
        color={SEARCH.iconColor}
        weight="regular"
      />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        style={{
          flex: 1,
          minWidth: 0,
          backgroundColor: "transparent",
          border: "none",
          outline: "none",
          color: SEARCH.text,
          fontFamily: FONT.family,
          fontSize: px(FONT.body2.size),
          lineHeight: `${px(FONT.body2.height)}px`,
        }}
      />
    </div>
  );
}

// ────── View ─────────────────────────────────────────────────────────────
export default function StorefrontView() {
  const { px } = useFigmaPx();
  const { dispatch, ACTIONS } = useWorkflow();
  const [tools, setTools] = useState([]);
  const [sharedTools, setSharedTools] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [busyId, setBusyId] = useState(null);
  const [showSubmitDialog, setShowSubmitDialog] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setLoading(true);
        const [marketplaceData, sharedData] = await Promise.all([
          fetchMarketplaceWorkflows(0, 100),
          fetchVisibleSharedTools().catch(() => ({ items: [] })),
        ]);
        if (!cancelled) {
          setTools(marketplaceData.items || marketplaceData.workflows || []);
          setSharedTools(sharedData.items || []);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || "Failed to load tools");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (!search.trim()) return tools;
    const q = search.toLowerCase();
    return tools.filter(
      (t) =>
        (t.marketplaceName || t.name || "").toLowerCase().includes(q) ||
        (t.marketplaceDescription || t.description || "")
          .toLowerCase()
          .includes(q),
    );
  }, [tools, search]);

  const filteredSharedTools = useMemo(() => {
    if (!search.trim()) return sharedTools;
    const q = search.toLowerCase();
    return sharedTools.filter(
      (t) =>
        (t.tool_name || "").toLowerCase().includes(q) ||
        (t.description || "").toLowerCase().includes(q),
    );
  }, [sharedTools, search]);

  // Legacy EXTERNAL_APPS removed — shared tools from DB serve this role now.

  const sharedAsApps = useMemo(
    () =>
      filteredSharedTools.map((st) => ({
        id: st.id,
        name: st.tool_name,
        description: st.description || "",
        link: st.url,
        icon: st.icon_url || null,
      })),
    [filteredSharedTools],
  );

  const spotlightItems = useMemo(
    () => buildSpotlightItems(filtered, sharedAsApps),
    [filtered, sharedAsApps],
  );

  const spotlightIds = useMemo(
    () => new Set(spotlightItems.map((item) => item.id)),
    [spotlightItems],
  );

  const gridAgents = useMemo(
    () => filtered.filter((t) => !spotlightIds.has(t.id)),
    [filtered, spotlightIds],
  );

  const gridSharedApps = useMemo(
    () => sharedAsApps.filter((a) => !spotlightIds.has(a.id)),
    [sharedAsApps, spotlightIds],
  );

  const hasCatalog =
    !loading && !error && (filtered.length > 0 || sharedAsApps.length > 0);
  const isEmpty =
    !loading && !error && filtered.length === 0 && sharedAsApps.length === 0;
  const hasGridCatalog = gridAgents.length > 0 || gridSharedApps.length > 0;

  const launchWithProject = async (tool, projectId) => {
    setBusyId(tool.id);
    try {
      const session = await createChatSession(tool.id, {
        name: `Chat with ${tool.marketplaceName || tool.name}`,
        project_id: projectId || undefined,
      });
      dispatch({
        type: ACTIONS.NAVIGATE,
        payload: {
          view: "chat",
          selectedWorkflow: tool,
          selectedSession: session,
        },
      });
    } catch (e) {
      safeError("Failed to start chat from storefront:", e);
      setError(e.message || "Failed to start chat");
    } finally {
      setBusyId(null);
    }
  };

  const handleStart = async (tool) => {
    if (busyId) return;
    await launchWithProject(tool, null);
  };

  return (
    <div
      className="storefront-page w-full"
      style={{
        backgroundColor: LAYOUT.pageBg,
        color: COLOR.white,
        fontFamily: FONT.family,
      }}
    >
      <div className="storefront-ambient" aria-hidden="true">
        <div className="storefront-ambient__glow storefront-ambient__glow--hero" />
        <div className="storefront-ambient__glow storefront-ambient__glow--catalog" />
        <div className="storefront-ambient__vignette" />
        <div className="storefront-ambient__grain" />
      </div>

      <div className="storefront-page__scroll w-full">
        <div
          className="storefront-page__main"
          style={{
            paddingLeft: px(LAYOUT.storefront.leftPaddingX),
            paddingRight: px(LAYOUT.storefront.leftPaddingX),
            paddingTop: px(10),
          }}
        >
          <header className="storefront-page__header">
            <h1
              className="storefront-page__title"
              style={{
                fontFamily: FONT.family,
                fontSize: px(FONT.sub1Bold.size),
                lineHeight: `${px(FONT.sub1Bold.height)}px`,
                fontWeight: FONT.sub1Bold.weight,
              }}
            >
              AI Marketplace
            </h1>

            <div
              className="storefront-page__toolbar"
              style={{
                maxWidth: `min(${px(LAYOUT.storefront.leftWidth)}px, 60vw)`,
              }}
            >
              <div
                style={{ display: "flex", gap: px(12), alignItems: "center" }}
              >
                <div style={{ flex: 1 }}>
                  <SearchInput
                    value={search}
                    onChange={setSearch}
                    placeholder="Search Store"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => setShowSubmitDialog(true)}
                  style={{
                    height: px(SEARCH.height),
                    paddingLeft: px(16),
                    paddingRight: px(16),
                    borderRadius: px(SEARCH.radius),
                    backgroundColor: COLOR.rose,
                    color: COLOR.white,
                    border: "none",
                    fontFamily: FONT.family,
                    fontSize: px(FONT.body2.size),
                    fontWeight: 600,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                    flexShrink: 0,
                  }}
                >
                  + Submit a Tool
                </button>
              </div>
            </div>
          </header>

          <section
            className="storefront-page__catalog"
            style={{ marginTop: px(28) }}
          >
            {loading && <ApexStorefrontLoading />}
            {error && !loading && (
              <div style={{ color: COLOR.rose, fontSize: px(FONT.body2.size) }}>
                {error}
              </div>
            )}
            {isEmpty && (
              <ApexShellEmpty
                title={search ? "No matching tools" : "No tools yet"}
                description={
                  search
                    ? "Try a different search term."
                    : "Tools shared to the marketplace will appear here when they are available."
                }
              />
            )}

            {hasCatalog && spotlightItems.length > 0 && (
              <StorefrontSpotlight
                items={spotlightItems}
                busyId={busyId}
                onStart={handleStart}
              />
            )}

            {hasCatalog && hasGridCatalog && (
              <>
                {gridAgents.length > 0 && (
                  <div
                    className={`storefront-catalog-block${spotlightItems.length > 0 ? " storefront-catalog-block--after-spotlight" : ""}`}
                  >
                    <SectionHeader
                      title="Apex OS Agents"
                      count={gridAgents.length}
                    />
                    <div className="storefront-card-grid">
                      {gridAgents.map((tool) => (
                        <ToolCard
                          key={tool.id}
                          tool={tool}
                          busy={busyId === tool.id}
                          onAction={handleStart}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {gridSharedApps.length > 0 && (
                  <div className="storefront-catalog-block">
                    <SectionHeader
                      title="Strategy& Tools"
                      count={gridSharedApps.length}
                    />
                    <div className="storefront-card-grid">
                      {gridSharedApps.map((app) => (
                        <ExternalAppCard key={app.id} app={app} />
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>

      {showSubmitDialog && (
        <SubmitToolDialog onClose={() => setShowSubmitDialog(false)} />
      )}
    </div>
  );
}
