import React, { useEffect, useRef, useState } from 'react';
import { Phone, SendHorizontal } from 'lucide-react';
import { ScreenContainer } from '../shared/ScreenContainer';

type CompanionStage = 'chat' | 'awaiting_confirmation' | 'consultation_active';

export interface CompanionChatMessage {
  id: string;
  role: 'assistant' | 'user' | 'system';
  text: string;
}

interface Screen7Props {
  onCallAgent?: () => void;
  messages: CompanionChatMessage[];
  isSendingMessage: boolean;
  companionStage: CompanionStage;
  onSendMessage: (text: string) => Promise<void>;
}

export const Screen7 = ({
  onCallAgent,
  messages,
  isSendingMessage,
  companionStage,
  onSendMessage,
}: Screen7Props) => {
  const [draft, setDraft] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const forceScrollNextRef = useRef(false);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const phonePulse = companionStage === 'awaiting_confirmation';
  const hasUserSentMessage = messages.some((message) => message.role === 'user');

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) {
      return;
    }
    el.scrollTop = el.scrollHeight;
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) {
      return;
    }
    if (forceScrollNextRef.current || isNearBottom) {
      el.scrollTop = el.scrollHeight;
      forceScrollNextRef.current = false;
    }
  }, [messages, isNearBottom]);

  const handleSend = async () => {
    const text = draft.trim();
    if (!text) {
      return;
    }
    setDraft('');
    forceScrollNextRef.current = true;
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    await onSendMessage(text);
  };

  return (
    <ScreenContainer>
      <div className="pt-20 pb-4 border-b border-gray-100 flex items-end justify-between px-6 bg-white shrink-0 dark:bg-black dark:border-white/10 transition-colors duration-300">
        <div>
          <h2 className="text-xl font-sans font-medium text-onyx dark:text-white transition-colors duration-300">
            AI Companion
          </h2>
        </div>
        <button
          onClick={() => {
            onCallAgent?.();
          }}
          className="w-10 h-10 border border-gray-200 flex items-center justify-center rounded-full bg-white hover:bg-black hover:border-black transition-colors group relative mb-1 dark:bg-[#3B3B3D] dark:border-white/10 dark:hover:bg-white dark:hover:text-onyx"
        >
          <Phone
            size={16}
            className="text-onyx group-hover:text-white transition-colors dark:text-white dark:group-hover:text-onyx"
          />
          {phonePulse && (
            <div className="absolute -top-1 -right-1 w-2 h-2 bg-red-600 rounded-full animate-pulse dark:bg-red-400"></div>
          )}
        </button>
      </div>
      <div
        ref={scrollRef}
        onScroll={(event) => {
          const el = event.currentTarget;
          const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
          setIsNearBottom(distanceToBottom <= 48);
        }}
        className="flex-1 overflow-y-auto scrollbar-hide p-6 space-y-8"
      >
        {messages.map((msg) => {
          if (msg.role === 'system')
            return (
              <div key={msg.id} className="flex items-center gap-4">
                <div className="h-px flex-1 bg-gray-200 dark:bg-white/10"></div>
                <span className="text-[9px] font-mono text-gray-400 uppercase tracking-widest dark:text-[#A3A3A3]">
                  {msg.text}
                </span>
                <div className="h-px flex-1 bg-gray-200 dark:bg-white/10"></div>
              </div>
            );

          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="flex justify-end">
                <div className="max-w-[82%] bg-onyx text-white p-4 rounded-2xl rounded-tr-sm text-xs leading-relaxed dark:bg-white dark:text-onyx transition-colors duration-300">
                  {msg.text}
                </div>
              </div>
            );
          }

          return (
            <div key={msg.id} className="flex gap-4">
              <div className="w-6 pt-1 text-right shrink-0">
                <span className="text-[9px] font-mono font-bold text-onyx uppercase dark:text-white">
                  AI
                </span>
              </div>
              <div className="flex-1 max-w-[90%]">
                <div className="bg-white border border-gray-200 p-4 rounded-2xl rounded-tl-sm text-xs text-onyx leading-relaxed shadow-sm dark:bg-[#3B3B3D] dark:border-white/5 dark:text-[#E6E6E7] transition-colors duration-300">
                  {msg.text}
                </div>
              </div>
            </div>
          );
        })}
        {isSendingMessage && (
          <div className="flex gap-4">
            <div className="w-6 pt-1 text-right shrink-0">
              <span className="text-[9px] font-mono font-bold text-onyx uppercase dark:text-white">
                AI
              </span>
            </div>
            <div className="flex-1 max-w-[90%]">
              <div className="inline-flex items-center gap-1.5 bg-white border border-gray-200 px-4 py-3 rounded-2xl rounded-tl-sm shadow-sm dark:bg-[#3B3B3D] dark:border-white/5">
                {[0, 1, 2].map((index) => (
                  <span
                    key={index}
                    className="h-1.5 w-1.5 rounded-full bg-gray-400 dark:bg-[#A3A3A3] animate-bounce"
                    style={{
                      animationDelay: `${index * 0.12}s`,
                      animationDuration: '0.9s',
                    }}
                  />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="p-4 border-t border-gray-100 bg-white dark:bg-black dark:border-white/10 transition-colors duration-300">
        <div className="min-h-12 border border-gray-200 bg-white flex items-end px-3 py-2 justify-between text-gray-400 hover:border-gray-400 transition-colors rounded-xl dark:bg-[#3B3B3D] dark:border-white/5 dark:text-[#A3A3A3] dark:hover:border-white/20 gap-2">
          <textarea
            ref={textareaRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onInput={(event) => {
              const el = event.currentTarget;
              el.style.height = 'auto';
              el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void handleSend();
              }
            }}
            placeholder={hasUserSentMessage ? '' : 'Ask the AI Companion'}
            rows={1}
            className="flex-1 resize-none overflow-y-auto bg-transparent text-sm text-onyx placeholder:text-gray-400 focus:outline-none dark:text-white dark:placeholder:text-[#A3A3A3]"
            aria-label="Chat with AI Companion"
          />
          <button
            type="button"
            onClick={() => {
              void handleSend();
            }}
            disabled={!draft.trim()}
            className="disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Send message"
          >
            <SendHorizontal size={15} className="text-onyx dark:text-white" />
          </button>
        </div>
      </div>
    </ScreenContainer>
  );
};
