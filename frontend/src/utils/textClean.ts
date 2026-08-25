/**
 * 清除markdown渲染带来的不可见特殊字符、多余光标、零宽符号
 */
export function stripCursorArtifacts(text: string): string {
    if (!text) return text;
    return text
        .replace(/[\u200B\u200C\u200D\uFEFF\u007C]/g, "")
        .trimEnd();
}
