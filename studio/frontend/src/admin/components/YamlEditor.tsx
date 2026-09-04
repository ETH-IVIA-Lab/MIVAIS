import { yaml } from "@codemirror/lang-yaml";
import CodeMirror from "@uiw/react-codemirror";

export function YamlEditor({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return <CodeMirror value={value} height="560px" extensions={[yaml()]} onChange={onChange} />;
}
