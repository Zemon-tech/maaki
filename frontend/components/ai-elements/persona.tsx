"use client";

import { cn } from "@/lib/utils";
import type { RiveParameters } from "@rive-app/react-webgl2";
import {
  useRive,
  useStateMachineInput,
} from "@rive-app/react-webgl2";
import type { FC, ReactNode } from "react";
import { memo, useEffect, useMemo, useRef, useState } from "react";

// Delays Rive initialization by one frame so that React Strict Mode's
// immediate unmount cycle never creates a WebGL2 context. Only the
// second (real) mount will initialise, avoiding context exhaustion.
const useStrictModeSafeInit = () => {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setReady(true));
    return () => {
      cancelAnimationFrame(id);
      setReady(false);
    };
  }, []);

  return ready;
};

export type PersonaState =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "asleep";

interface PersonaProps {
  state: PersonaState;
  onLoad?: RiveParameters["onLoad"];
  onLoadError?: RiveParameters["onLoadError"];
  onReady?: () => void;
  onPause?: RiveParameters["onPause"];
  onPlay?: RiveParameters["onPlay"];
  onStop?: RiveParameters["onStop"];
  className?: string;
  variant?: keyof typeof sources;
}

// The state machine name is always 'default' for Elements AI visuals
const stateMachine = "default";

const sources = {
  command: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/command-2.0.riv",
  },
  glint: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/glint-2.0.riv",
  },
  halo: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/halo-2.0.riv",
  },
  mana: {
    dynamicColor: false,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/mana-2.0.riv",
  },
  obsidian: {
    dynamicColor: true,
    hasModel: true,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/obsidian-2.0.riv",
  },
  opal: {
    dynamicColor: false,
    hasModel: false,
    source:
      "https://ejiidnob33g9ap1r.public.blob.vercel-storage.com/orb-1.2.riv",
  },
};

const getCurrentTheme = (): "light" | "dark" => {
  if (typeof window !== "undefined") {
    if (document.documentElement.classList.contains("dark")) {
      return "dark";
    }
    if (window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
      return "dark";
    }
  }
  return "light";
};

const useTheme = (enabled: boolean) => {
  const [theme, setTheme] = useState<"light" | "dark">(getCurrentTheme);

  useEffect(() => {
    // Skip if not enabled (avoids unnecessary observers for non-dynamic-color variants)
    if (!enabled) {
      return;
    }

    // Watch for classList changes
    const observer = new MutationObserver(() => {
      setTheme(getCurrentTheme());
    });

    observer.observe(document.documentElement, {
      attributeFilter: ["class"],
      attributes: true,
    });

    // Watch for OS-level theme changes
    let mql: MediaQueryList | null = null;
    const handleMediaChange = () => {
      setTheme(getCurrentTheme());
    };

    if (window.matchMedia) {
      mql = window.matchMedia("(prefers-color-scheme: dark)");
      mql.addEventListener("change", handleMediaChange);
    }

    return () => {
      observer.disconnect();
      if (mql) {
        mql.removeEventListener("change", handleMediaChange);
      }
    };
  }, [enabled]);

  return theme;
};

interface PersonaThemerProps {
  rive: ReturnType<typeof useRive>["rive"];
  dynamicColor: boolean;
  children: React.ReactNode;
}

const PersonaThemer = memo(({ rive, dynamicColor, children }: PersonaThemerProps) => {
  const theme = useTheme(dynamicColor);

  useEffect(() => {
    if (!rive || !dynamicColor) return;

    try {
      // Safely access Rive ViewModel if present on the loaded artboard
      const vm = (rive as unknown as { defaultViewModel?: () => unknown }).defaultViewModel?.();
      if (vm) {
        const instance = (vm as { defaultInstance?: () => unknown }).defaultInstance?.();
        if (instance) {
          const colorProp = (instance as { color?: (name: string) => { setRgb: (r: number, g: number, b: number) => void } }).color?.("color");
          if (colorProp && typeof colorProp.setRgb === "function") {
            const [r, g, b] = theme === "dark" ? [255, 255, 255] : [0, 0, 0];
            colorProp.setRgb(r, g, b);
          }
        }
      }
    } catch {
      // Artboard does not define a ViewModel or is loading
    }
  }, [rive, theme, dynamicColor]);

  return <>{children}</>;
});

PersonaThemer.displayName = "PersonaThemer";

const PersonaInner: FC<PersonaProps & { source: (typeof sources)[keyof typeof sources] }> = memo(
  ({
    state = "idle",
    onLoad,
    onLoadError,
    onReady,
    onPause,
    onPlay,
    onStop,
    className,
    source,
  }) => {
    // Stabilize callbacks to prevent useRive from reinitializing
    const callbacksRef = useRef({
      onLoad,
      onLoadError,
      onPause,
      onPlay,
      onReady,
      onStop,
    });

    useEffect(() => {
      callbacksRef.current = {
        onLoad,
        onLoadError,
        onPause,
        onPlay,
        onReady,
        onStop,
      };
    }, [onLoad, onLoadError, onPause, onPlay, onReady, onStop]);

    const stableCallbacks = useMemo(
      () => ({
        onLoad: ((loadedRive) =>
          callbacksRef.current.onLoad?.(
            loadedRive
          )) as RiveParameters["onLoad"],
        onLoadError: ((err) =>
          callbacksRef.current.onLoadError?.(
            err
          )) as RiveParameters["onLoadError"],
        onPause: ((event) =>
          callbacksRef.current.onPause?.(event)) as RiveParameters["onPause"],
        onPlay: ((event) =>
          callbacksRef.current.onPlay?.(event)) as RiveParameters["onPlay"],
        onReady: () => callbacksRef.current.onReady?.(),
        onStop: ((event) =>
          callbacksRef.current.onStop?.(event)) as RiveParameters["onStop"],
      }),
      []
    );

    // Delay initialisation by one frame to avoid creating (and leaking)
    // a WebGL2 context during React Strict Mode's first throw-away mount.
    const ready = useStrictModeSafeInit();

    const { rive, RiveComponent } = useRive(
      ready
        ? {
            autoplay: true,
            onLoad: stableCallbacks.onLoad,
            onLoadError: stableCallbacks.onLoadError,
            onPause: stableCallbacks.onPause,
            onPlay: stableCallbacks.onPlay,
            onRiveReady: stableCallbacks.onReady,
            onStop: stableCallbacks.onStop,
            src: source.source,
            stateMachines: stateMachine,
          }
        : null
    );

    const listeningInput = useStateMachineInput(
      rive,
      stateMachine,
      "listening"
    );
    const thinkingInput = useStateMachineInput(rive, stateMachine, "thinking");
    const speakingInput = useStateMachineInput(rive, stateMachine, "speaking");
    const asleepInput = useStateMachineInput(rive, stateMachine, "asleep");

    // Rive state machine inputs are mutable objects that must be set via direct
    // property assignment — this is the intended Rive API, not a React anti-pattern.
    useEffect(() => {
      if (listeningInput) {
        listeningInput.value = state === "listening";
      }
      if (thinkingInput) {
        thinkingInput.value = state === "thinking";
      }
      if (speakingInput) {
        speakingInput.value = state === "speaking";
      }
      if (asleepInput) {
        asleepInput.value = state === "asleep";
      }
    }, [state, listeningInput, thinkingInput, speakingInput, asleepInput]);

    return (
      <PersonaThemer rive={rive} dynamicColor={Boolean(source.dynamicColor)}>
        <RiveComponent className={cn("size-16 shrink-0", className)} />
      </PersonaThemer>
    );
  }
);

PersonaInner.displayName = "PersonaInner";

export const Persona: FC<PersonaProps> = memo((props) => {
  const variant = props.variant || "opal";
  const source = sources[variant] || sources.opal;

  return (
    <PersonaInner
      key={`${variant}-${source.source}`}
      {...props}
      variant={variant}
      source={source}
    />
  );
});

Persona.displayName = "Persona";
