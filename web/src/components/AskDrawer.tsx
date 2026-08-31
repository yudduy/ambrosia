import { useEffect, useRef, useState } from "react";
import { Button, Checkbox, InlineLoading, TextArea } from "@carbon/react";
import { Chat, Close, Login, Send } from "@carbon/icons-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

interface Message {
  role: "user" | "assistant" | "system";
  text: string;
}

export function AskDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [accepted, setAccepted] = useState(() => localStorage.getItem("ambrosia-ai-disclosure") === "accepted");
  const [threadId, setThreadId] = useState<string>();
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const eventSource = useRef<EventSource | undefined>(undefined);
  const endRef = useRef<HTMLDivElement>(null);
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: api.assistantStatus, enabled: open });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => () => eventSource.current?.close(), []);

  async function login() {
    setError(undefined);
    try {
      const result = await api.assistantLogin();
      const url = result.authUrl ?? result.verificationUrl;
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start ChatGPT sign-in.");
    }
  }

  function connectEvents(id: string) {
    eventSource.current?.close();
    const source = new EventSource(`/api/assistant/threads/${id}/events`);
    eventSource.current = source;
    source.addEventListener("message_delta", (event) => {
      const { text } = JSON.parse((event as MessageEvent).data) as { text: string };
      setMessages((current) => {
        const last = current.at(-1);
        if (last?.role === "assistant") {
          return [...current.slice(0, -1), { ...last, text: last.text + text }];
        }
        return [...current, { role: "assistant", text }];
      });
    });
    source.addEventListener("turn_completed", (event) => {
      const value = JSON.parse((event as MessageEvent).data) as { status: string; error?: unknown };
      setSending(false);
      if (value.status !== "completed") setError("The AI turn did not complete. Your dashboard data was not changed.");
    });
    source.onerror = () => setSending(false);
    return new Promise<void>((resolve, reject) => {
      source.onopen = () => resolve();
      setTimeout(() => reject(new Error("Assistant event stream timed out.")), 10_000);
    });
  }

  async function send() {
    const text = draft.trim();
    if (!text || sending) return;
    setError(undefined);
    setSending(true);
    setDraft("");
    setMessages((current) => [...current, { role: "user", text }]);
    try {
      let id = threadId;
      if (!id) {
        const thread = await api.createAssistantThread("Health consultation");
        id = thread.id;
        setThreadId(id);
        await connectEvents(id);
      }
      await api.assistantTurn(id, text);
    } catch (reason) {
      setSending(false);
      setError(reason instanceof Error ? reason.message : "Could not send this question.");
    }
  }

  function acceptDisclosure(value: boolean) {
    setAccepted(value);
    if (value) localStorage.setItem("ambrosia-ai-disclosure", "accepted");
    else localStorage.removeItem("ambrosia-ai-disclosure");
  }

  return (
    <aside className={`ask-drawer ${open ? "ask-drawer--open" : ""}`} aria-hidden={!open} aria-label="Ask Ambrosia">
      <header className="ask-drawer__header">
        <div className="ask-drawer__title"><Chat size={20} /> <span>Ask Ambrosia</span></div>
        <button className="icon-button" onClick={onClose} aria-label="Close Ask Ambrosia"><Close size={20} /></button>
      </header>
      {!accepted ? (
        <div className="disclosure">
          <p className="eyebrow">Before the first conversation</p>
          <h2>Your dashboard stays local until you ask.</h2>
          <p>When AI is invoked, selected health summaries, your message, and any meal image you choose are sent to OpenAI through your ChatGPT account.</p>
          <p>Routine sync, comparisons, and weekly reports remain on this Mac.</p>
          <Checkbox
            id="ai-disclosure"
            labelText="I understand what is sent when I use AI"
            checked={accepted}
            onChange={(_, state) => acceptDisclosure(Boolean(state.checked))}
          />
        </div>
      ) : status.isLoading ? (
        <InlineLoading description="Checking private AI connection" />
      ) : !status.data?.authenticated ? (
        <div className="assistant-login">
          <p className="eyebrow">ChatGPT connection</p>
          <h2>Sign in once on this Mac.</h2>
          <p>{status.data?.reason ?? "Ambrosia uses Codex app-server so it does not store an OpenAI API key."}</p>
          <Button renderIcon={Login} onClick={login}>Sign in with ChatGPT</Button>
          <button className="text-button" onClick={() => status.refetch()}>I finished signing in</button>
        </div>
      ) : (
        <>
          <div className="messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="assistant-intro">
                <span className="assistant-mark">A</span>
                <h2>Ask about what changed.</h2>
                <p>I can inspect the same covered summaries you see here—never unrestricted health records.</p>
                <div className="prompt-chips">
                  {["Why is my HRV lower?", "Help me plan this week", "Could sodium explain how I feel?"].map((prompt) => (
                    <button key={prompt} onClick={() => setDraft(prompt)}>{prompt}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`message message--${message.role}`}>
                <span>{message.role === "assistant" ? "Ambrosia" : "You"}</span>
                <p>{message.text}</p>
              </div>
            ))}
            {sending && <InlineLoading description="Looking at covered evidence" />}
            <div ref={endRef} />
          </div>
          <div className="composer">
            <TextArea
              id="assistant-message"
              labelText="Question"
              hideLabel
              placeholder="Ask about sleep, training, nutrition, or recovery…"
              value={draft}
              rows={3}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <Button hasIconOnly iconDescription="Send question" renderIcon={Send} disabled={!draft.trim() || sending} onClick={send} />
          </div>
        </>
      )}
      {error && <div className="drawer-error" role="alert">{error}</div>}
      <footer className="ask-drawer__footer">Exploratory guidance · not medical advice</footer>
    </aside>
  );
}
