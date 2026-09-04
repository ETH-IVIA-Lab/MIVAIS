import { useCallback, useState } from "react";
import { useCursorTracking } from "mivais-va-client/react";
import { usePodium } from "../context";
import { ChatPanel } from "../components/ChatPanel";
import type { ChatToOption } from "../components/ChatPanel";
import { CursorOverlay } from "../components/CursorOverlay";
import { Header } from "./Header";
import { RankingPanel } from "./RankingPanel";
import { WeightColumn } from "./WeightColumn";

export function Dashboard() {
  const { sessionId, cursors, connectedUsers, onlineAgents, chatHistory, sendChat, sendCursor, canPublish } = usePodium();
  const [highlight, setHighlight] = useState<{ name: string; nonce: number } | null>(null);
  useCursorTracking(sendCursor);

  const onHighlightRow = useCallback((name: string) => {
    setHighlight((prev) => ({ name, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  const toOptions: ChatToOption[] = [
    { value: "broadcast", label: "Everyone" },
    ...onlineAgents.map((a) => ({ value: a.id, label: `${a.id} (${a.role})` })),
    ...connectedUsers
      .filter((u) => u.session_id !== sessionId)
      .map((u) => ({ value: `user:${u.session_id}`, label: `${u.session_id.slice(0, 6)} (${u.role})` })),
  ];

  return (
    <>
      <Header />
      <main>
        <WeightColumn />
        <RankingPanel highlightRowName={highlight?.name} highlightNonce={highlight?.nonce} />
      </main>
      <CursorOverlay cursors={cursors} ownSessionId={sessionId} />
      <ChatPanel
        messages={chatHistory}
        ownSessionId={sessionId}
        toOptions={toOptions}
        canSend={canPublish("chat.message")}
        onSend={sendChat}
        onHighlightRow={onHighlightRow}
      />
    </>
  );
}
