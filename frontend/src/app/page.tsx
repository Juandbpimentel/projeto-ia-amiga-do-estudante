import { ChatPanel } from "@/components/chat/chat-panel";

export default function Home() {
  return (
    <main className="app-shell">
      <section className="hero">
        <small className="hero-pill">Campus Quixadá</small>
        <h1>IA amiga do estudante</h1>
        <p>
          Converse com o assistente oficial da UFC Quixadá para descobrir cardápio do RU,
          feriados do calendário acadêmico, status dos sistemas ou contatos de professores.
        </p>
      </section>
      <ChatPanel />
    </main>
  );
}
