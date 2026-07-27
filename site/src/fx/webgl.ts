/** 极光与画廊波纹共用的全屏 quad WebGL1 工具层。
    任一环节失败(拿不到上下文/编译/链接/抛异常)一律返回 null，调用方走静态降级。 */

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
  try {
    const gl = canvas.getContext("webgl");
    if (!gl) return null;
    const compile = (type: number, src: string): WebGLShader | null => {
      const s = gl.createShader(type);
      if (!s) return null;
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (gl.getShaderParameter(s, gl.COMPILE_STATUS)) return s;
      // shader 报错的唯一出口：静默 null 在真机上表现为「画布全空、控制台无声」，
      // T10 极光/T15 波纹靠分支预览调 shader，缺这条信号等于蒙眼调。DEV 门控，生产零成本。
      if (import.meta.env.DEV)
        console.warn("[fx/webgl]", gl.getShaderInfoLog(s));
      gl.deleteShader(s);
      return null;
    };
    const vs = compile(gl.VERTEX_SHADER, VERT);
    const fs = compile(gl.FRAGMENT_SHADER, fragSrc);
    if (!vs || !fs) {
      // 一成一败时把成功的那个回收掉，否则孤儿 shader 一直挂在 context 上
      if (vs) gl.deleteShader(vs);
      if (fs) gl.deleteShader(fs);
      return null;
    }
    const prog = gl.createProgram();
    if (!prog) {
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      return null;
    }
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      if (import.meta.env.DEV)
        console.warn("[fx/webgl]", gl.getProgramInfoLog(prog));
      gl.deleteProgram(prog);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      return null;
    }
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
        // 依赖 WEBGL_lose_context，缺失时为 no-op；当前消费方卸载即弃 canvas，可接受。
        gl.getExtension("WEBGL_lose_context")?.loseContext();
      },
    };
  } catch {
    // GPU 黑名单、隐私模式等环境下 getContext 会直接抛而非返回 null。
    // 「失败即 null」是全站静态降级契约的根，异常也必须收敛成 null。
    return null;
  }
}
