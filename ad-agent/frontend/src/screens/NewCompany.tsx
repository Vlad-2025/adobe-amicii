import { useState } from "react";
import { Button, Flex, Heading, NumberField, Text, TextArea, TextField } from "@adobe/react-spectrum";
import { post, queryClient } from "../api";
import { Card } from "../components/ui";

const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export default function NewCompany() {
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [description, setDescription] = useState("");
  const [tone, setTone] = useState("clear and friendly");
  const [banned, setBanned] = useState("");
  const [competitors, setCompetitors] = useState("");
  const [aov, setAov] = useState(50);
  const [conv, setConv] = useState("purchase");
  const [cvr, setCvr] = useState(4);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await post("/api/companies", { name, industry, description, tone, banned_phrases: split(banned), competitors: split(competitors), avg_order_value: aov, conversion_name: conv, base_cvr: cvr / 100 });
      queryClient.invalidateQueries();
      window.location.hash = `/company/${r.company_id}`;
    } catch (e: any) {
      setErr(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Flex direction="column" gap="size-250" maxWidth={760}>
      <a href="#/companies" style={{ color: "inherit", opacity: 0.6, fontSize: 13 }}>← Companies</a>
      <Heading level={2} margin={0}>New company profile</Heading>
      <Text UNSAFE_style={{ opacity: 0.75 }}>The profile is what the agents work from: the brand kit drives the copy and the brand guard, the economics turn clicks into € figures. Connect channels on the next screen.</Text>
      <Card title="Company">
        <Flex direction="column" gap="size-150">
          <TextField label="Name" value={name} onChange={setName} isRequired width="100%" />
          <TextField label="What you sell" value={industry} onChange={setIndustry} isRequired width="100%" description="e.g. Organic dog treats (D2C)" />
          <TextArea label="Short description" value={description} onChange={setDescription} width="100%" />
        </Flex>
      </Card>
      <Card title="Brand kit">
        <Flex direction="column" gap="size-150">
          <TextField label="Tone of voice" value={tone} onChange={setTone} width="100%" />
          <TextField label="Banned phrases (comma separated)" value={banned} onChange={setBanned} width="100%" />
          <TextField label="Competitors, never named in ads (comma separated)" value={competitors} onChange={setCompetitors} width="100%" />
        </Flex>
      </Card>
      <Card title="Economics">
        <Flex gap="size-200" wrap>
          <TextField label="A conversion is a…" value={conv} onChange={setConv} description="purchase, trial signup, wishlist…" />
          <NumberField label="Average value per conversion (€)" value={aov} onChange={setAov} minValue={0.5} />
          <NumberField label="Typical conversion rate (% of clicks)" value={cvr} onChange={setCvr} minValue={0.5} maxValue={60} />
        </Flex>
      </Card>
      {err && <Text UNSAFE_style={{ color: "#e34850" }}>{err}</Text>}
      <Button variant="cta" onPress={create} isPending={busy} isDisabled={name.length < 2 || industry.length < 2} alignSelf="start">Create company</Button>
    </Flex>
  );
}
