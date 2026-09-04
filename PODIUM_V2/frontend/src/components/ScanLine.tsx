export function ScanLine({ variant, run, nonce }: { variant: "svm" | "adv"; run: boolean; nonce: number }) {
  return <div key={nonce} className={`scan-line ${variant}-beam${run ? " run" : ""}`} />;
}
