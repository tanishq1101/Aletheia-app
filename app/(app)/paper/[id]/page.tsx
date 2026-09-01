import PaperReader from "@/components/PaperReader";

export default async function PaperReaderPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <PaperReader paperId={id} />;
}
