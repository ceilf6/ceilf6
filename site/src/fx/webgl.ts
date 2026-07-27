/** 极光与画廊波纹共用的全屏 quad WebGL1 工具层。
    任一环节失败(拿不到上下文/编译/链接)一律返回 null，调用方走静态降级。 */

const VERT =
  "attribute vec2 p; varying vec2 uv; void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0.,1.); }";

export interface QuadProgram {
  gl: WebGLRenderingContext;
  uniform(name: string): WebGLUniformLocation | null;
  draw(): void;
  destroy(): void;
}

export function initQuadProgram(
  canvas: HTMLCanvasElement,
  fragSrc: string,
): QuadProgram | null {
  const gl = canvas.getContext("webgl");
  if (!gl) return null;
  const compile = (type: number, src: string): WebGLShader | null => {
    const s = gl.createShader(type);
    if (!s) return null;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null;
  };
  const vs = compile(gl.VERTEX_SHADER, VERT);
  const fs = compile(gl.FRAGMENT_SHADER, fragSrc);
  if (!vs || !fs) return null;
  const prog = gl.createProgram();
  if (!prog) return null;
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
    gl.STATIC_DRAW,
  );
  const loc = gl.getAttribLocation(prog, "p");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  return {
    gl,
    uniform: (name) => gl.getUniformLocation(prog, name),
    draw: () => gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4),
    destroy: () => {
      gl.getExtension("WEBGL_lose_context")?.loseContext();
    },
  };
}
