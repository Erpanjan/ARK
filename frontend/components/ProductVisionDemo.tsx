'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import { PhoneFrame } from './product-vision/shared/PhoneFrame';
import { ScreenLogo } from './product-vision/screens/ScreenLogo';
import { Screen1 } from './product-vision/screens/Screen1';
import { Screen2 } from './product-vision/screens/Screen2';
import { Screen3 } from './product-vision/screens/Screen3';
import { ScreenWait } from './product-vision/screens/ScreenWait';
import { Screen4 } from './product-vision/screens/Screen4';
import { ScreenFinancialDiagnoses } from './product-vision/screens/ScreenFinancialDiagnoses';
import { Screen5 } from './product-vision/screens/Screen5';
import { Screen6 } from './product-vision/screens/Screen6';
import { Screen7 } from './product-vision/screens/Screen7';
import { useConsultationVoiceAgent } from '@/hooks/useConsultationVoiceAgent';
import { usePolicyExplanationVoiceAgent } from '@/hooks/usePolicyExplanationVoiceAgent';
import { buildReferenceFallbackPolicy } from '@/lib/policy/fallback';
import type { ConsultationTurn, FinalPolicy } from '@/lib/policy/types';

type RetryPayload = {
  sessionId: string;
  turns: ConsultationTurn[];
  completionReason: 'agent' | 'user';
};

const normalizeText = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

const guessSectionKeyFromMessage = (
  message: string,
  sections: Array<{ id: string; title: string }>
): string | null => {
  if (!message.trim() || sections.length === 0) {
    return null;
  }

  const taggedMatch = message.match(/\[\[SECTION:([a-zA-Z0-9_-]+)\]\]/i);
  if (taggedMatch?.[1]) {
    const matchedId = taggedMatch[1].trim();
    if (sections.some((section) => section.id === matchedId)) {
      return matchedId;
    }
  }

  const normalizedMessage = normalizeText(message);
  for (const section of sections) {
    const normalizedTitle = normalizeText(section.title);
    if (normalizedTitle && normalizedMessage.includes(normalizedTitle)) {
      return section.id;
    }
  }

  return null;
};

export default function ProductVisionDemo() {
  const [currentScreen, setCurrentScreen] = useState(1);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [policy, setPolicy] = useState<FinalPolicy | null>(() =>
    buildReferenceFallbackPolicy('loading')
  );
  const [isPolicyLoading, setIsPolicyLoading] = useState(false);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [retryPayload, setRetryPayload] = useState<RetryPayload | null>(null);

  const {
    status: consultationVoiceStatus,
    mode: consultationVoiceMode,
    error: consultationVoiceError,
    isMuted: consultationVoiceMuted,
    inputVolume: consultationVoiceInputVolume,
    outputVolume: consultationVoiceOutputVolume,
    transcript,
    disconnectReason,
    startSession: startConsultationVoiceSession,
    prewarmSession: prewarmConsultationVoiceSession,
    endSession: endConsultationVoiceSession,
    toggleMute: toggleConsultationMute,
    clearTranscript: clearConsultationTranscript,
  } = useConsultationVoiceAgent();
  const {
    status: policyVoiceStatus,
    isPlaying: isPolicyVoicePlaying,
    activeSectionKey: policyVoiceActiveSectionKey,
    lastAgentMessage: policyVoiceLastAgentMessage,
    start: startPolicyVoiceExplanation,
    stop: stopPolicyVoiceExplanation,
  } = usePolicyExplanationVoiceAgent();

  const menuData = policy?.menu ?? {
    title: 'Recommended Policy',
    summary: 'Policy generated from consultation context.',
  };

  const detailData = policy?.detail ?? {
    title: 'Policy Breakdown',
    sections: [],
    portfolio: {
      currency: 'USD',
      total_value: null,
      securities: [],
    },
  };
  const financialDiagnoses = policy?.financial_diagnoses ?? [];
  const fallbackLabel = policy?.ui_generation?.fallback_used
    ? policy.ui_generation.fallback_label || 'Reference fallback content'
    : null;
  const fallbackMessage = policy?.ui_generation?.fallback_used
    ? policy.ui_generation.fallback_message || null
    : null;

  const policyVoiceContext = useMemo(() => {
    const sections = detailData.sections || [];
    const orderedSections = sections
      .map((section, index) => `${index + 1}. ${section.title}\n${section.content}`)
      .join('\n\n');

    return [
      `Policy Title: ${detailData.title || menuData.title}`,
      `Objective Summary: ${menuData.summary}`,
      'Explain this policy as a guided walkthrough in the same section order below.',
      orderedSections,
    ]
      .filter(Boolean)
      .join('\n\n');
  }, [detailData.sections, detailData.title, menuData.summary, menuData.title]);

  const derivedPolicyVoiceSectionKey = useMemo(
    () =>
      policyVoiceActiveSectionKey ??
      guessSectionKeyFromMessage(policyVoiceLastAgentMessage, detailData.sections || []),
    [policyVoiceActiveSectionKey, policyVoiceLastAgentMessage, detailData.sections]
  );

  const runPolicyPipeline = useCallback(async (payload: RetryPayload) => {
    setPolicy(buildReferenceFallbackPolicy('loading'));
    setCurrentScreen(5);
    setIsPolicyLoading(true);
    setPolicyError(null);
    setRetryPayload(payload);

    try {
      const response = await fetch('/api/policy/from-consultation', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          session_id: payload.sessionId,
          turns: payload.turns,
          completion_reason: payload.completionReason,
        }),
      });

      const body = await response.json();
      if (!response.ok || !body?.success || !body?.policy) {
        throw new Error(body?.error || `Policy pipeline failed (${response.status})`);
      }

      setPolicy(body.policy as FinalPolicy);
      setIsPolicyLoading(false);
      setPolicyError(null);
      setCurrentScreen(6);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Policy generation failed';
      setPolicy(buildReferenceFallbackPolicy('failed', message));
      setIsPolicyLoading(false);
      setPolicyError(message);
    }
  }, []);

  const handleConsultationEnd = useCallback(
    (reason: 'agent' | 'user') => {
      const orderedTurns: ConsultationTurn[] = [...transcript]
        .map((turn) => ({
          role: turn.role,
          message: turn.message,
          timestamp: turn.timestamp,
        }))
        .filter((turn) => turn.message.trim().length > 0)
        .sort((a, b) => a.timestamp - b.timestamp);

      const payload: RetryPayload = {
        sessionId: `consult-${Date.now()}`,
        turns: orderedTurns,
        completionReason: reason,
      };
      void runPolicyPipeline(payload);
    },
    [runPolicyPipeline, transcript]
  );

  const handleRetryPolicy = useCallback(() => {
    if (!retryPayload) {
      return;
    }
    void runPolicyPipeline(retryPayload);
  }, [retryPayload, runPolicyPipeline]);

  const screens = useMemo(
    () => [
      { id: 1, component: <ScreenLogo onNext={() => setCurrentScreen(2)} /> },
      { id: 2, component: <Screen1 onNext={() => setCurrentScreen(3)} /> },
      { id: 3, component: <Screen2 onNext={() => setCurrentScreen(4)} /> },
      {
        id: 4,
        component: (
          <Screen3
            onConsultationEnd={handleConsultationEnd}
            onSwitchToChat={() => setCurrentScreen(10)}
            isDarkMode={isDarkMode}
            voiceStatus={consultationVoiceStatus}
            voiceMode={consultationVoiceMode}
            voiceError={consultationVoiceError}
            voiceIsMuted={consultationVoiceMuted}
            voiceInputVolume={consultationVoiceInputVolume}
            voiceOutputVolume={consultationVoiceOutputVolume}
            voiceTranscript={transcript}
            voiceDisconnectReason={disconnectReason}
            onStartVoiceSession={() => {
              void startConsultationVoiceSession();
            }}
            onEndVoiceSession={endConsultationVoiceSession}
            onToggleVoiceMute={toggleConsultationMute}
            onResetVoiceTranscript={clearConsultationTranscript}
          />
        ),
      },
      {
        id: 5,
        component: (
          <ScreenWait isLoading={isPolicyLoading} error={policyError} onRetry={handleRetryPolicy} />
        ),
      },
      {
        id: 6,
        component: (
          <ScreenFinancialDiagnoses
            diagnoses={financialDiagnoses}
            fallbackLabel={fallbackLabel}
            onNext={() => setCurrentScreen(7)}
          />
        ),
      },
      {
        id: 7,
        component: (
          <Screen4
            onAnalyzeDepth={() => setCurrentScreen(8)}
            menu={menuData}
            proposalIndex={policy?.proposal_index ?? 1}
            proposalCount={policy?.proposal_count ?? 1}
            fallbackLabel={fallbackLabel}
          />
        ),
      },
      {
        id: 8,
        component: (
          <Screen5
            onProceed={() => {
              void stopPolicyVoiceExplanation();
              setCurrentScreen(9);
            }}
            detail={detailData}
            activeVoiceSectionKey={derivedPolicyVoiceSectionKey}
            fallbackLabel={fallbackLabel}
            fallbackMessage={fallbackMessage}
            onToggleVoiceExplanation={() => {
              if (isPolicyVoicePlaying) {
                void stopPolicyVoiceExplanation();
                return;
              }
              void startPolicyVoiceExplanation(
                policyVoiceContext,
                (detailData.sections || []).map((section) => ({ id: section.id, title: section.title }))
              );
            }}
            isVoicePlaying={isPolicyVoicePlaying}
            voiceStatus={policyVoiceStatus}
          />
        ),
      },
      {
        id: 9,
        component: (
          <Screen6
            onExecute={() => setCurrentScreen(10)}
            execution={policy?.execution}
            fallbackCurrency={detailData?.portfolio?.currency || 'USD'}
          />
        ),
      },
      {
        id: 10,
        component: (
          <Screen7
            voiceStatus={consultationVoiceStatus}
            voiceError={consultationVoiceError}
            isVoiceMuted={consultationVoiceMuted}
            onStartVoiceSession={() => {
              void startConsultationVoiceSession();
            }}
            onEndVoiceSession={() => {
              void endConsultationVoiceSession();
            }}
            onToggleMute={() => {
              void toggleConsultationMute();
            }}
          />
        ),
      },
    ],
    [
      clearConsultationTranscript,
      consultationVoiceError,
      consultationVoiceInputVolume,
      consultationVoiceMode,
      consultationVoiceMuted,
      consultationVoiceOutputVolume,
      consultationVoiceStatus,
      detailData,
      disconnectReason,
      endConsultationVoiceSession,
      financialDiagnoses,
      handleConsultationEnd,
      handleRetryPolicy,
      isDarkMode,
      isPolicyLoading,
      menuData,
      policy,
      policyVoiceContext,
      derivedPolicyVoiceSectionKey,
      policyVoiceStatus,
      policyError,
      isPolicyVoicePlaying,
      startConsultationVoiceSession,
      startPolicyVoiceExplanation,
      stopPolicyVoiceExplanation,
      toggleConsultationMute,
      transcript,
    ]
  );

  const current = screens.find((screen) => screen.id === currentScreen) ?? screens[0];

  useEffect(() => {
    if (currentScreen !== 8 && isPolicyVoicePlaying) {
      void stopPolicyVoiceExplanation();
    }
  }, [currentScreen, isPolicyVoicePlaying, stopPolicyVoiceExplanation]);

  useEffect(() => {
    if (currentScreen === 4) {
      void prewarmConsultationVoiceSession();
    }
  }, [currentScreen, prewarmConsultationVoiceSession]);

  return (
    <div className="flex flex-col items-center">
      <PhoneFrame statusBarTime="09:41" isDarkMode={isDarkMode}>
        {current.component}
      </PhoneFrame>

      <div className="mt-4 flex items-center justify-center gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCurrentScreen((prev) => Math.max(1, prev - 1))}
            disabled={currentScreen === 1}
            className="h-9 w-9 rounded-full border border-white/20 bg-black/50 text-white backdrop-blur-sm disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center"
            aria-label="Previous screen"
          >
            <ChevronLeft size={16} />
          </button>

          {screens.map((screen) => (
            <button
              key={screen.id}
              onClick={() => setCurrentScreen(screen.id)}
              className={`h-2.5 w-2.5 rounded-full transition-all ${currentScreen === screen.id ? 'bg-white scale-110' : 'bg-white/40 hover:bg-white/70'
                }`}
              aria-label={`Go to screen ${screen.id}`}
            />
          ))}

          <button
            onClick={() => setCurrentScreen((prev) => Math.min(10, prev + 1))}
            disabled={currentScreen === 10}
            className="h-9 w-9 rounded-full border border-white/20 bg-black/50 text-white backdrop-blur-sm disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center"
            aria-label="Next screen"
          >
            <ChevronRight size={16} />
          </button>
        </div>

        <button
          onClick={() => setIsDarkMode((prev) => !prev)}
          className="ml-2 h-9 px-3 rounded-full border border-white/20 bg-black/50 text-white text-xs uppercase tracking-wider backdrop-blur-sm"
        >
          {isDarkMode ? 'Light' : 'Dark'}
        </button>
      </div>
    </div>
  );
}
