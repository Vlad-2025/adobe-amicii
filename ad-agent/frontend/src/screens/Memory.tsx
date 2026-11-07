import { Flex, Heading, ProgressCircle, Text } from "@adobe/react-spectrum";
import { useApi } from "../api";
import { Card } from "../components/ui";

export default function Memory() {
  const q = useApi<any[]>("memory", "/api/memory");
  if (!q.data) return <ProgressCircle isIndeterminate aria-label="loading" />;
  return (
    <Flex direction="column" gap="size-250">
      <Heading level={2} margin={0}>Marketing memory</Heading>
      <Text UNSAFE_style={{ opacity: 0.7 }}>
        Learnings from finished experiments. Before the strategist writes variants it retrieves the 3 closest learnings plus every loser for that community.
      </Text>
      {q.data.map((m) => (
        <Card key={m.id}>
          <Flex gap="size-150" alignItems="start">
            <span style={{ fontSize: 18, fontWeight: 800, color: m.winner ? "#2d9d78" : "#e34850" }}>{m.winner ? "✓" : "✕"}</span>
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
