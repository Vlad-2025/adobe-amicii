import { Flex, Heading, ProgressCircle, Text } from "@adobe/react-spectrum";
import { useApi , C } from "../api";
import { Card, Info } from "../components/ui";

export default function Memory() {
  const q = useApi<any[]>("memory", C("/memory"));
  if (!q.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  return (
    <Flex direction="column" gap="size-250">
      <Flex alignItems="center" gap="size-100">
        <Heading level={2} margin={0}>Marketing memory</Heading>
        <Info>Learnings from finished experiments. Before writing new variants, the AI reads the 3 closest learnings and every past loser for that community.</Info>
      </Flex>
      {q.data.map((m) => (
        <Card key={m.id}>
          <Flex gap="size-150" alignItems="start">
            <span style={{ fontSize: 18, fontWeight: 800, color: m.winner ? "var(--green)" : "var(--red)" }}>{m.winner ? "✓" : "✕"}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 15 }}>{m.insight}</div>
              <div style={{ fontSize: 13, opacity: 0.7, marginTop: 4 }}>Evidence: {m.evidence}</div>
              <div style={{ fontSize: 12, opacity: 0.55, marginTop: 4 }}>
                Applies to: {m.applies_to.community ?? m.applies_to.pack} · {String(m.applies_to.dimension).replace("_", " ")} · {m.created_day < 0 ? `${-m.created_day} days before the simulation` : `day ${m.created_day}`}
              </div>
            </div>
          </Flex>
        </Card>
      ))}
    </Flex>
  );
}
