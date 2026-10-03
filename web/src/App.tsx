import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import { ExampleTemplates } from "./components/ExampleTemplates";
import { GenerationSettingsCard } from "./components/GenerationSettingsCard";
import { HeroSection } from "./components/HeroSection";
import { IconExplorerCard } from "./components/IconExplorerCard";
import { PromptCard } from "./components/PromptCard";
import { ResultCard } from "./components/ResultCard";
import { Sidebar, type NavKey } from "./components/Sidebar";
import { TopBar } from "./components/TopBar";
import {
  ApiError,
  generateDiagram,
  getHealth,
  type CompilationResponse,
  type LlmOverride,
  type Provider,
} from "./lib/api";

const DIAGRAMS_LIMIT = 50;

export default function App() {
  const [activeNav, setActiveNav] = useState<NavKey>("create");
  const [prompt, setPrompt] = useState("");
  const [provider, setProvider] = useState<Provider>("aws");
  const [llm, setLlm] = useState<LlmOverride>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompilationResponse | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [diagramsUsed, setDiagramsUsed] = useState(0);

  useEffect(() => {
    getHealth()
      .then(() => setBackendOnline(true))
      .catch(() => setBackendOnline(false));
  }, []);

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    try {
      const response = await generateDiagram({
        prompt,
        provider,
        llm: llm.api_key || llm.endpoint || llm.model ? llm : undefined,
      });
      setResult(response);
      setDiagramsUsed((count) => Math.min(DIAGRAMS_LIMIT, count + 1));
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong while generating the diagram.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen bg-bg">
      <Sidebar
        active={activeNav}
        onNavigate={setActiveNav}
        backendOnline={backendOnline}
        diagramsUsed={diagramsUsed}
        diagramsLimit={DIAGRAMS_LIMIT}
      />

      <div className="flex min-h-screen flex-1 flex-col">
        <TopBar backendOnline={backendOnline} />

        <main className="flex-1 overflow-y-auto px-8 py-8">
          <div className="mx-auto max-w-6xl">
            <HeroSection />

            <div className="mt-8 grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
              <div className="min-w-0 space-y-5">
                <PromptCard
                  prompt={prompt}
                  onPromptChange={setPrompt}
                  provider={provider}
                  onProviderChange={setProvider}
                  onSubmit={handleSubmit}
                  loading={loading}
                  error={error}
                />

                <ExampleTemplates onUseExample={setPrompt} />

                <AnimatePresence mode="wait">
                  {result && (
                    <motion.div
                      key={result.diagram_id}
                      className="min-w-0"
                      exit={{ opacity: 0, y: -12 }}
                    >
                      <ResultCard result={result} />
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              <div className="min-w-0 space-y-5">
                <GenerationSettingsCard llm={llm} onLlmChange={setLlm} />
                <IconExplorerCard provider={provider} />
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
