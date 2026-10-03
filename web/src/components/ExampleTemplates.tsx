import { motion } from "framer-motion";
import { useState } from "react";

type Category = "All" | "Serverless" | "Web Application" | "Data & Analytics" | "E-commerce" | "AI/ML" | "Multi-Cloud";

const CATEGORIES: Category[] = ["All", "Serverless", "Web Application", "Data & Analytics", "E-commerce", "AI/ML", "Multi-Cloud"];

interface ExampleTemplate {
  title: string;
  description: string;
  category: Category;
  prompt: string;
  chain: { label: string; color: string }[];
}

const EXAMPLES: ExampleTemplate[] = [
  {
    title: "Serverless API with Queue",
    description: "API Gateway, Lambda, SQS, Worker, DynamoDB with monitoring",
    category: "Serverless",
    prompt: "A serverless API with a queue-backed worker writing to a database, plus monitoring",
    chain: [
      { label: "API", color: "bg-node-networking" },
      { label: "λ", color: "bg-node-compute" },
      { label: "SQS", color: "bg-node-messaging" },
      { label: "DB", color: "bg-node-database" },
    ],
  },
  {
    title: "E-commerce Platform",
    description: "VPC, Load Balancer, ECS, RDS, ElastiCache, S3",
    category: "E-commerce",
    prompt: "An e-commerce platform behind a load balancer with containers, a managed database, a cache, and object storage",
    chain: [
      { label: "LB", color: "bg-node-networking" },
      { label: "ECS", color: "bg-node-compute" },
      { label: "RDS", color: "bg-node-database" },
      { label: "S3", color: "bg-node-storage" },
    ],
  },
  {
    title: "Data Processing Pipeline",
    description: "S3, Lambda, Glue, Redshift, QuickSight",
    category: "Data & Analytics",
    prompt: "A data pipeline that ingests files into object storage, transforms them with a managed ETL job, and loads them into a data warehouse for analytics",
    chain: [
      { label: "S3", color: "bg-node-storage" },
      { label: "λ", color: "bg-node-compute" },
      { label: "ETL", color: "bg-node-messaging" },
      { label: "DW", color: "bg-node-database" },
    ],
  },
  {
    title: "Multi-Cloud Architecture",
    description: "Connect services across AWS, Azure, and Google Cloud",
    category: "Multi-Cloud",
    prompt: "A multi-cloud architecture connecting services across AWS, Azure, and Google Cloud",
    chain: [
      { label: "AWS", color: "bg-provider-aws" },
      { label: "⇄", color: "bg-text-tertiary" },
      { label: "AZ", color: "bg-provider-azure" },
      { label: "GC", color: "bg-provider-gcp" },
    ],
  },
];

interface ExampleTemplatesProps {
  onUseExample: (prompt: string) => void;
}

export function ExampleTemplates({ onUseExample }: ExampleTemplatesProps) {
  const [category, setCategory] = useState<Category>("All");
  const visible = category === "All" ? EXAMPLES : EXAMPLES.filter((item) => item.category === category);

  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-semibold text-text-primary">Or try an example</h3>
          <div className="flex flex-wrap gap-1.5">
            {CATEGORIES.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setCategory(item)}
                className={`rounded-full px-2.5 py-1 text-xs transition-colors ${
                  category === item
                    ? "bg-brand-soft font-medium text-brand-active"
                    : "text-text-tertiary hover:bg-bg-subtle hover:text-text-secondary"
                }`}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        <button type="button" className="shrink-0 text-xs font-medium text-brand hover:text-brand-hover">
          View all examples →
        </button>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {visible.map((example, index) => (
          <motion.div
            key={example.title}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: index * 0.05 }}
            className="flex flex-col rounded-xl border border-border bg-surface p-4 shadow-card transition-shadow hover:shadow-elevated"
          >
            <div className="flex items-center gap-1.5">
              {example.chain.map((node, nodeIndex) => (
                <div key={nodeIndex} className="flex items-center gap-1.5">
                  <span
                    className={`grid h-7 w-7 shrink-0 place-items-center rounded-md text-[10px] font-semibold text-white ${node.color}`}
                  >
                    {node.label}
                  </span>
                  {nodeIndex < example.chain.length - 1 && (
                    <span className="text-text-disabled">→</span>
                  )}
                </div>
              ))}
            </div>

            <h4 className="mt-3 text-sm font-semibold text-text-primary">{example.title}</h4>
            <p className="mt-1 flex-1 text-xs leading-relaxed text-text-tertiary">{example.description}</p>

            <button
              type="button"
              onClick={() => onUseExample(example.prompt)}
              className="mt-3 flex items-center gap-1 self-start rounded-lg border border-border px-2.5 py-1.5 text-xs font-medium text-text-secondary transition-colors hover:border-brand hover:text-brand"
            >
              Use this example →
            </button>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
