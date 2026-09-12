import { Button } from '@gouvfr-lasuite/cunningham-react';
import { CSSProperties, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import styled from 'styled-components';

import { useConfig } from '@/core';

/**
 * Mosa app switcher. Same trigger (colored dot grid) and panel ("You're in" /
 * "Jump to") as the switcher in Mail, Docs and Drive, so switching apps feels
 * identical across the suite. The list of reachable apps comes from the backend
 * `theme_customization.app_switcher` map (app id → root URL), served from
 * configuration/theme/mosa.json.
 */

type AppId =
  | 'ai'
  | 'epicentre'
  | 'docs'
  | 'drive'
  | 'meet'
  | 'mail'
  | 'calendar'
  | 'chat'
  | 'commander';

const APP_META: Record<
  AppId,
  {
    icon: string;
    label: string;
    subtitle: string;
    color: string;
    gradientEnd: string;
  }
> = {
  ai: {
    icon: '/assets/icons/ai-icon.svg',
    label: 'ai',
    subtitle: 'Assistant',
    color: '#6D8BFF',
    gradientEnd: '#0443F2',
  },
  epicentre: {
    icon: '/assets/icons/epicentre-icon.svg',
    label: 'Hub',
    subtitle: 'Home',
    color: '#0284C7',
    gradientEnd: '#0443F2',
  },
  docs: {
    icon: '/assets/icons/file-icon.svg',
    label: 'Docs',
    subtitle: 'Documents',
    color: '#06B6D4',
    gradientEnd: '#0891B2',
  },
  drive: {
    icon: '/assets/icons/folder-icon.svg',
    label: 'Drive',
    subtitle: 'Files',
    color: '#F2AF05',
    gradientEnd: '#D97706',
  },
  meet: {
    icon: '/assets/icons/camera-icon.svg',
    label: 'Meet',
    subtitle: 'Video calls',
    color: '#00B574',
    gradientEnd: '#059669',
  },
  mail: {
    icon: '/assets/icons/mail-icon.svg',
    label: 'Mail',
    subtitle: 'Email',
    color: '#F8497B',
    gradientEnd: '#A0033A',
  },
  calendar: {
    icon: '/assets/icons/calendar-icon.svg',
    label: 'Calendar',
    subtitle: 'Schedule',
    color: '#A78BFA',
    gradientEnd: '#6D3FDE',
  },
  chat: {
    icon: '/assets/icons/chat-icon.svg',
    label: 'Chat',
    subtitle: 'Messaging',
    color: '#FA7108',
    gradientEnd: '#C2410C',
  },
  commander: {
    icon: '/assets/icons/commander-icon.svg',
    label: 'Commander',
    subtitle: 'Admin',
    color: '#0284C7',
    gradientEnd: '#0064C8',
  },
};

const CURRENT_APP: AppId = 'ai';

// Fixed order for the trigger button's decorative dot pattern — identical
// across every Mosa app regardless of which app is current (matches Mail/Docs/Drive).
const DOT_ORDER: AppId[] = [
  'epicentre',
  'drive',
  'meet',
  'mail',
  'calendar',
  'chat',
  'commander',
];

// The current app is intentionally omitted — it never appears in the jump-to list.
const NAV_ORDER: AppId[] = [
  'epicentre',
  'docs',
  'drive',
  'meet',
  'mail',
  'calendar',
  'chat',
  'commander',
];

const MOBILE_BREAKPOINT = 480;

const StyledAppSwitcher = styled.div`
  --mosa-surface: #ffffff;
  --mosa-border: #e6eaf1;
  --mosa-ink: #333333;
  --mosa-graphite: #5a6577;

  position: relative;
  display: flex;
  align-items: center;

  .app-switcher__trigger-grid {
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--mosa-border);
    border-radius: 6px;
    padding: 5px;
  }

  .app-switcher__dropdown {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    width: 312px;
    background: var(--mosa-surface);
    border: 1px solid var(--mosa-border);
    border-radius: 16px;
    box-shadow:
      0 2px 4px rgba(0, 0, 0, 0.02),
      0 4px 8px rgba(0, 0, 0, 0.03),
      0 8px 16px rgba(0, 0, 0, 0.04),
      0 16px 32px rgba(0, 0, 0, 0.05),
      0 32px 64px rgba(0, 0, 0, 0.08);
    padding: 14px;
    z-index: 2000;
    animation: mosa-panel-in 150ms cubic-bezier(0.4, 0, 0.2, 1) both;

    &.app-switcher__dropdown--up {
      top: auto;
      bottom: calc(100% + 8px);
    }

    @media (max-width: ${MOBILE_BREAKPOINT}px) {
      position: fixed;
      left: 1rem;
      right: 1rem;
      margin: 0 auto;
      width: auto;
      max-width: 312px;
      max-height: calc(100vh - 2rem);
      overflow-y: auto;
    }
  }

  @keyframes mosa-panel-in {
    from {
      opacity: 0;
      transform: translateY(-4px) scale(0.98);
    }
    to {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
  }

  .app-switcher__icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .app-switcher__current {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 2px 4px 10px;
  }

  .app-switcher__current-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .app-switcher__you-are-in,
  .app-switcher__section-label {
    font-family: 'Poppins', system-ui, sans-serif;
    font-size: 0.6875rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--mosa-graphite);
  }

  .app-switcher__app-name {
    font-family: 'Poppins', system-ui, sans-serif;
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--mosa-ink);
  }

  .app-switcher__divider {
    height: 1px;
    background: var(--mosa-border);
    margin: 4px -14px 14px;
  }

  .app-switcher__section-label {
    display: block;
    padding: 0 4px;
    margin-bottom: 8px;
  }

  .app-switcher__grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px;
  }

  .app-switcher__app {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px;
    border-radius: 10px;
    text-decoration: none;
    transition: background 120ms cubic-bezier(0.4, 0, 0.2, 1);

    &:hover {
      background: #f7f8fa;
    }
  }

  .app-switcher__app-info {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .app-switcher__app-label {
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--mosa-ink);
  }

  .app-switcher__app-subtitle {
    font-size: 0.6875rem;
    color: var(--mosa-graphite);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
`;

const AppIcon = ({ id, size = 40 }: { id: AppId; size?: number }) => {
  const { icon, label, color, gradientEnd } = APP_META[id];
  const radius = size <= 36 ? 9 : 12;
  return (
    <span
      className="app-switcher__icon"
      style={{
        width: size,
        height: size,
        borderRadius: radius,
        background: `linear-gradient(135deg, ${color} 0%, ${gradientEnd} 100%)`,
      }}
    >
      <img
        src={icon}
        alt={label}
        style={{ width: size * 0.45, height: size * 0.45 }}
      />
    </span>
  );
};

const Panel = ({
  onClose,
  opensUpward,
  appUrls,
  anchorRect,
}: {
  onClose: () => void;
  opensUpward: boolean;
  appUrls: Record<string, string>;
  anchorRect: DOMRect | null;
}) => {
  const { t } = useTranslation();

  const jumpTo = NAV_ORDER.filter((id) => id in appUrls && id in APP_META);

  const isMobile =
    typeof window !== 'undefined' && window.innerWidth <= MOBILE_BREAKPOINT;
  const mobilePosition: CSSProperties = {};
  if (isMobile && anchorRect) {
    if (opensUpward) {
      mobilePosition.top = 'auto';
      mobilePosition.bottom = window.innerHeight - anchorRect.top + 8;
    } else {
      mobilePosition.top = anchorRect.bottom + 8;
      mobilePosition.bottom = 'auto';
    }
  }

  return (
    <div
      className={`app-switcher__dropdown${opensUpward ? ' app-switcher__dropdown--up' : ''}`}
      style={{
        background: `linear-gradient(180deg, color-mix(in srgb, ${APP_META[CURRENT_APP].color} 8%, transparent) 0%, transparent 100%) top center / 100% 80px no-repeat, #ffffff`,
        ...mobilePosition,
      }}
    >
      <div className="app-switcher__current">
        <AppIcon id={CURRENT_APP} size={44} />
        <div className="app-switcher__current-text">
          <span className="app-switcher__you-are-in">{t("You're in")}</span>
          <span className="app-switcher__app-name">
            {APP_META[CURRENT_APP].label}
          </span>
        </div>
      </div>

      {jumpTo.length > 0 && (
        <>
          <div className="app-switcher__divider" />
          <span className="app-switcher__section-label">{t('Jump to')}</span>
          <div className="app-switcher__grid">
            {jumpTo.map((id) => (
              <a
                key={id}
                href={appUrls[id]}
                className="app-switcher__app"
                onClick={onClose}
              >
                <AppIcon id={id} size={36} />
                <div className="app-switcher__app-info">
                  <span className="app-switcher__app-label">
                    {APP_META[id].label}
                  </span>
                  <span className="app-switcher__app-subtitle">
                    {APP_META[id].subtitle}
                  </span>
                </div>
              </a>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export const AppSwitcher = () => {
  const { data: conf } = useConfig();
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [opensUpward, setOpensUpward] = useState(false);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  const appUrls = conf?.theme_customization?.app_switcher ?? {};
  const hasOtherApps = NAV_ORDER.some((id) => id in appUrls && id in APP_META);

  const measure = () => {
    if (!ref.current) {
      return;
    }
    const rect = ref.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const spaceAbove = rect.top;
    setOpensUpward(spaceBelow < spaceAbove);
    setAnchorRect(rect);
  };

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    window.addEventListener('resize', measure);
    window.addEventListener('orientationchange', measure);
    return () => {
      document.removeEventListener('mousedown', handler);
      window.removeEventListener('resize', measure);
      window.removeEventListener('orientationchange', measure);
    };
  }, [isOpen]);

  if (!hasOtherApps) {
    return null;
  }

  const handleOpen = () => {
    measure();
    setIsOpen((v) => !v);
  };

  return (
    <StyledAppSwitcher ref={ref}>
      <Button
        color="brand"
        variant="tertiary"
        aria-label={t('Switch app')}
        aria-expanded={isOpen}
        onClick={handleOpen}
        icon={
          <span className="app-switcher__trigger-grid" aria-hidden>
            <svg width="18" height="18" viewBox="0 0 18 18">
              {[...DOT_ORDER, DOT_ORDER[0], DOT_ORDER[1]].map((id, i) => (
                <circle
                  key={i}
                  cx={3 + (i % 3) * 6}
                  cy={3 + Math.floor(i / 3) * 6}
                  r={2}
                  fill={APP_META[id].color}
                />
              ))}
            </svg>
          </span>
        }
      />
      {isOpen && (
        <Panel
          onClose={() => setIsOpen(false)}
          opensUpward={opensUpward}
          appUrls={appUrls}
          anchorRect={anchorRect}
        />
      )}
    </StyledAppSwitcher>
  );
};
