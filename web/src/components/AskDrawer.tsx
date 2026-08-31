import { useEffect, useRef, useState } from "react";
import { Button, Checkbox, InlineLoading, TextArea } from "@carbon/react";
import { Chat, Close, Image, Login, Send, TrashCan } from "@carbon/icons-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { AssistantMessage } from "../lib/types";

interface PendingPhoto {
  file: File;
  previewUrl: string;
}

export function AskDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [accepted, setAccepted] = useState(() => localStorage.getItem("ambrosia-ai-disclosure") === "accepted");
  const [threadId, setThreadId] = useState<string>();
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [photo, setPhoto] = useState<PendingPhoto>();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string>();
  const eventSource = useRef<EventSource | undefined>(undefined);
  const connectedThread = useRef<string | undefined>(undefined);
  const fileInput = useRef<HTMLInputElement>(null);
  const photoUrl = useRef<string | undefined>(undefined);
  const endRef = useRef<HTMLDivElement>(null);
  const status = useQuery({
    queryKey: ["assistant-status"], queryFn: api.assistantStatus,
    enabled: open && accepted,
  });
  const conversation = useQuery({
    queryKey: ["assistant-conversation"], queryFn: api.assistantConversation,
    enabled: open && accepted && status.data?.authenticated === true,
  });

  useEffect(() => {
    if (!conversation.data) return;
    setThreadId(conversation.data.thread?.id);
    setMessages(conversation.data.messages);
  }, [conversation.data]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => () => {
    eventSource.current?.close();
    if (photoUrl.current) URL.revokeObjectURL(photoUrl.current);
  }, []);

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
    if (connectedThread.current === id && eventSource.current?.readyState !== EventSource.CLOSED) {
      return Promise.resolve();
    }
    eventSource.current?.close();
    const source = new EventSource(`/api/assistant/threads/${id}/events?live=true`);
    eventSource.current = source;
    connectedThread.current = id;
    source.addEventListener("message_delta", (event) => {
      const { text } = JSON.parse((event as MessageEvent).data) as { text: string };
      setMessages((current) => {
        const last = current.at(-1);
        if (last?.role === "assistant") {
          return [...current.slice(0, -1), { ...last, text: last.text + text }];
        }
        return [...current, {
          id: crypto.randomUUID(), role: "assistant", text,
          image_url: null, created_at: new Date().toISOString(),
        }];
      });
    });
    source.addEventListener("message_completed", (event) => {
      const { text } = JSON.parse((event as MessageEvent).data) as { text: string };
      setMessages((current) => {
        const last = current.at(-1);
        if (last?.role === "assistant") return [...current.slice(0, -1), { ...last, text }];
        return [...current, {
          id: crypto.randomUUID(), role: "assistant", text,
          image_url: null, created_at: new Date().toISOString(),
        }];
      });
    });
    source.addEventListener("turn_completed", (event) => {
      const value = JSON.parse((event as MessageEvent).data) as { status: string; error?: unknown };
      setSending(false);
      void queryClient.invalidateQueries({ queryKey: ["assistant-conversation"] });
      if (value.status !== "completed") setError("The reply stopped. Your question is still in the chat.");
    });
    source.onerror = () => setSending(false);
    return new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error("Could not connect to the chat.")), 10_000);
      source.onopen = () => {
        window.clearTimeout(timeout);
        resolve();
      };
    });
  }

  async function send() {
    const text = draft.trim() || (photo ? "What can you tell me about this meal? Estimate calories and macros as ranges." : "");
    if (!text || sending) return;
    const optimisticId = crypto.randomUUID();
    setError(undefined);
    setSending(true);
    setDraft("");
    setMessages((current) => [...current, {
      id: optimisticId, role: "user", text,
      image_url: photo?.previewUrl ?? null, created_at: new Date().toISOString(),
    }]);
    try {
      let id = threadId;
      if (!id) {
        const thread = await api.createAssistantThread("My health chat");
        id = thread.id;
        setThreadId(id);
      }
      await connectEvents(id);
      let imageDraftId: string | undefined;
      if (photo) {
        const uploaded = await api.uploadMeal(photo.file, "");
        imageDraftId = uploaded.id;
        setMessages((current) => current.map((message) => (
          message.id === optimisticId ? { ...message, image_url: uploaded.thumbnail_url } : message
        )));
      }
      await api.assistantTurn(id, text, imageDraftId);
      if (photo) {
        URL.revokeObjectURL(photo.previewUrl);
        photoUrl.current = undefined;
        setPhoto(undefined);
      }
    } catch (reason) {
      setSending(false);
      setError(reason instanceof Error ? reason.message : "Could not send this message.");
    }
  }

  function choosePhoto(file?: File) {
    if (!file) return;
    if (photoUrl.current) URL.revokeObjectURL(photoUrl.current);
    const previewUrl = URL.createObjectURL(file);
    photoUrl.current = previewUrl;
    setPhoto({ file, previewUrl });
    setError(undefined);
  }

  function removePhoto() {
    if (photo) URL.revokeObjectURL(photo.previewUrl);
    photoUrl.current = undefined;
    setPhoto(undefined);
    if (fileInput.current) fileInput.current.value = "";
  }

  function acceptDisclosure(value: boolean) {
    setAccepted(value);
    if (value) localStorage.setItem("ambrosia-ai-disclosure", "accepted");
    else localStorage.removeItem("ambrosia-ai-disclosure");
  }

  return (
    <aside className={`ask-drawer ${open ? "ask-drawer--open" : ""}`} aria-hidden={!open} aria-label="Health chat">
      <header className="ask-drawer__header">
        <div className="ask-drawer__title"><Chat size={20} /> <span>Health chat</span></div>
        <button className="icon-button" onClick={onClose} aria-label="Close health chat"><Close size={20} /></button>
      </header>
      {!accepted ? (
        <div className="disclosure">
          <h2>Before you start</h2>
          <p>Your messages, the health summaries used to answer them, and any photo you attach are sent to OpenAI. Your full health database stays on this Mac.</p>
          <Checkbox
            id="ai-disclosure"
            labelText="I understand"
            checked={accepted}
            onChange={(_, state) => acceptDisclosure(Boolean(state.checked))}
          />
        </div>
      ) : status.isLoading ? (
        <InlineLoading description="Connecting..." />
      ) : !status.data?.authenticated ? (
        <div className="assistant-login">
          <h2>Connect ChatGPT</h2>
          <p>Sign in once, then this chat will remember your conversation.</p>
          <Button renderIcon={Login} onClick={login}>Sign in with ChatGPT</Button>
          <button className="text-button" onClick={() => status.refetch()}>I signed in</button>
        </div>
      ) : conversation.isLoading ? (
        <InlineLoading description="Loading chat..." />
      ) : (
        <>
          <div className="messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="assistant-intro">
                <h2>What do you want to know?</h2>
                <p>I can look across your sleep, fitness, food, and recent history.</p>
                <div className="prompt-chips">
                  {["How am I doing lately?", "Why is my HRV lower?", "Help me plan this week"].map((prompt) => (
                    <button key={prompt} onClick={() => setDraft(prompt)}>{prompt}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((message) => (
              <div key={message.id} className={`message message--${message.role}`}>
                <span>{message.role === "assistant" ? "Ambrosia" : "You"}</span>
                {message.image_url && <img src={message.image_url} alt="Meal attached to this message" onError={(event) => { event.currentTarget.hidden = true; }} />}
                <p>{message.text}</p>
              </div>
            ))}
            {sending && <InlineLoading description="Thinking..." />}
            <div ref={endRef} />
          </div>
          <div className="composer">
            {photo && (
              <div className="composer-photo">
                <img src={photo.previewUrl} alt="Photo ready to send" />
                <span>{photo.file.name}</span>
                <Button hasIconOnly kind="ghost" size="sm" iconDescription="Remove photo" renderIcon={TrashCan} onClick={removePhoto} />
              </div>
            )}
            <div className="composer-row">
              <input
                ref={fileInput}
                className="visually-hidden"
                type="file"
                accept="image/jpeg,image/png,image/webp,image/heic"
                capture="environment"
                onChange={(event) => choosePhoto(event.target.files?.[0])}
              />
              <Button hasIconOnly kind="ghost" iconDescription="Attach meal photo" renderIcon={Image} onClick={() => fileInput.current?.click()} />
              <TextArea
                id="assistant-message"
                labelText="Message"
                hideLabel
                placeholder="Ask about your health"
                value={draft}
                rows={2}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void send();
                  }
                }}
              />
              <Button hasIconOnly iconDescription="Send message" renderIcon={Send} disabled={(!draft.trim() && !photo) || sending} onClick={send} />
            </div>
          </div>
        </>
      )}
      {error && <div className="drawer-error" role="alert">{error}</div>}
      <footer className="ask-drawer__footer">Not medical advice</footer>
    </aside>
  );
}
