<script setup>
/** 设置页：表单由后端 config_schema 自动生成，加配置项前端不用改。
 *  分「基础」与折叠的「高级」，逐字段中文说明常驻显示。 */
import { reactive, ref, computed, onMounted, watch } from "vue";
import { useStore, api, saveConfig, saveEnv, jsonBody, toast } from "../store.js";
import { UiCard, UiField, UiSwitch, UiSelect, UiBtn, UiTabs, UiSearch, UiBadge, UiListEditor } from "../ui";
import PromptPanel from "../components/PromptPanel.vue";

const s = useStore();
const schema = ref(null);
const tab = ref("basic");
const showAdvanced = ref(false);
const query = ref("");
const dirty = ref(false);
const saving = ref(false);
const verifying = ref("");
const testModel = ref("");   // 手填模型引用（提供商/模型）测试连通性

// 行式编辑器的列定义：providers（providerlist）与团队成员（agentlist）
const listColumns = {
  provider: [
    { key: "name", label: "名称（引用时用）", placeholder: "deepseek", width: "0.8" },
    { key: "base_url", label: "接口地址（OpenAI 兼容）", placeholder: "https://api.deepseek.com/v1", width: "2" },
    { key: "api_key", label: "密钥", placeholder: "sk-…", type: "password", width: "1.2" },
  ],
  agent: [
    { key: "name", label: "成员名", placeholder: "文风编辑", width: "0.8" },
    { key: "model", label: "模型（可 提供商/模型）", placeholder: "留空 = 主模型", width: "1.4" },
    { key: "thinking", label: "思考强度", type: "select", width: "0.6",
      options: [["", "关"], ["低", "低"], ["中", "中"], ["高", "高"]] },
    { key: "perspective", label: "职责视角", placeholder: "以什么身份评审、重点看什么", width: "2" },
  ],
};

const form = reactive({});
const envForm = reactive({});
const preset = ref("");

onMounted(async () => {
  try {
    schema.value = await api("/api/config-schema");
  } catch (e) { toast("读取配置定义失败：" + e.message, true); }
  syncFromState();
});

// config/env 变化（含首次加载）时回填
watch(() => s.config, syncFromState, { deep: true });
watch(() => s.env, syncFromState, { deep: true });

function syncFromState(){
  const c = s.config || {};
  for (const f of schema.value?.fields || []){
    form[f.path] = get(c, f.path, f.default);
  }
  for (const e of schema.value?.env || []){
    const cur = s.env?.[e.path];
    envForm[e.path] = e.secret ? "" : (cur?.value ?? "");
  }
  dirty.value = false;
}

function get(obj, dotted, fallback){
  return dotted.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj) ?? fallback;
}

const tabs = computed(() => [
  ...(schema.value?.groups || []).map(g => ({
    key: g.key,
    label: g.label,
    count: fieldsFor(g.key).length,
  })),
  { key: "prompts", label: "提示词" },
]);

// 当前分组的字段：搜索时跨分组匹配；高级项默认折叠
function fieldsFor(group){
  let list = (schema.value?.fields || []).filter(f => f.group === group);
  if (!showAdvanced.value) list = list.filter(f => !f.advanced);
  return list;
}

const visible = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return fieldsFor(tab.value);
  return (schema.value?.fields || []).filter(f =>
    !(!showAdvanced.value && f.advanced) &&
    (f.label.toLowerCase().includes(q) || f.path.toLowerCase().includes(q) ||
     (f.help || "").toLowerCase().includes(q)));
});

const advancedCount = computed(() =>
  (schema.value?.fields || []).filter(f => f.advanced).length);

async function save(){
  saving.value = true;
  try {
    const patch = {};
    for (const f of schema.value?.fields || []) patch[f.path] = form[f.path];
    await saveConfig(patch);
    const envPatch = {};
    for (const [k, v] of Object.entries(envForm)) if (v !== "" && v != null) envPatch[k] = v;
    if (Object.keys(envPatch).length) await saveEnv(envPatch);
    dirty.value = false;
  } catch (e) { toast(String(e.message || e), true); }
  saving.value = false;
}

function applyPreset(key){
  const p = (schema.value?.presets || []).find(x => x.key === key);
  if (!p) return;
  for (const [k, v] of Object.entries(p.values)) form[k] = v;
  preset.value = key;
  dirty.value = true;
  toast("已套用「" + p.label + "」，记得点保存");
}

async function verify(kind, modelRef){
  verifying.value = modelRef ? "model:" + modelRef : kind;
  try {
    // 验证接口读的是 .env 文件：先把手上的改动落盘，免得测的是旧值
    const envPatch = {};
    for (const [k, v] of Object.entries(envForm)) if (v !== "" && v != null) envPatch[k] = v;
    if (Object.keys(envPatch).length) await saveEnv(envPatch);
    const body = modelRef ? { model: modelRef.trim() } : {};
    const r = await api("/api/verify/" + kind, jsonBody(body));
    toast((modelRef ? "[" + modelRef + "] " : "") + r.note, !r.ok);
  } catch (e) { toast(String(e.message || e), true); }
  verifying.value = "";
}
</script>

<template>
  <div class="view">
    <!-- 预设 -->
    <UiCard title="一键预设" desc="不知道怎么填？先套一个预设，再按需微调。">
      <div class="presets">
        <button v-for="p in (schema?.presets || [])" :key="p.key"
                class="preset" :class="{ on: preset === p.key }"
                @click="applyPreset(p.key)">
          <b>{{ p.label }}</b>
          <span>{{ p.desc }}</span>
        </button>
      </div>
    </UiCard>

    <!-- 登录与模型：跑起来最少要配的 -->
    <UiCard title="登录与模型"
            desc="这两项没配对，后面什么都跑不了。填完点右边的按钮验证一下（会先保存再验证）。">
      <div class="grid2">
        <UiField v-for="e in (schema?.env || [])" :key="e.path"
                 :label="e.label" :help="e.help">
          <input v-if="e.secret" v-model="envForm[e.path]" type="password"
                 :placeholder="s.env?.[e.path]?.hint ? '已填写（' + s.env[e.path].hint + '）——留空=不修改' : '粘贴到这里'"
                 @input="dirty = true">
          <input v-else v-model="envForm[e.path]" type="text"
                 :placeholder="s.env?.[e.path]?.value || '未填'" @input="dirty = true">
        </UiField>
      </div>
      <div class="actions">
        <UiBtn :loading="verifying === 'lofter'" @click="verify('lofter')">验证登录</UiBtn>
        <UiBtn :loading="verifying === 'llm'" @click="verify('llm')">测试模型</UiBtn>
      </div>
      <UiField class="testother"
               label="测试其他模型"
               help="填模型引用测连通性：「提供商名/模型名」（在下方「模型提供商」分组里先配好）或纯模型名（走上面的主提供商）。">
        <div class="testrow">
          <input type="text" v-model="testModel" placeholder="例如 deepseek/deepseek-chat">
          <UiBtn :loading="verifying === 'model:' + testModel" :disabled="!testModel.trim()"
                 @click="verify('llm', testModel)">测试</UiBtn>
        </div>
      </UiField>
    </UiCard>

    <!-- 配置项 -->
    <UiCard>
      <template #extra>
        <template v-if="tab !== 'prompts'">
          <UiSearch v-model="query" placeholder="搜索配置项（如「并发」「字数」）" />
          <UiBtn size="sm" :class="{ on: showAdvanced }" @click="showAdvanced = !showAdvanced">
            {{ showAdvanced ? "隐藏高级" : "显示高级（" + advancedCount + "）" }}
          </UiBtn>
        </template>
      </template>

      <template v-if="!query || tab === 'prompts'">
        <UiTabs v-model="tab" :items="tabs" />
      </template>

      <!-- 提示词：独立编辑器，不走自动生成的表单 -->
      <PromptPanel v-if="tab === 'prompts'" />

      <template v-else>
        <div v-if="!visible.length" class="nores">没有匹配的配置项</div>

        <div class="fields">
          <template v-for="f in visible" :key="f.path">
            <!-- 布尔：开关 -->
            <UiSwitch v-if="f.type === 'bool'" v-model="form[f.path]"
                      :label="f.label" :help="f.help"
                      @update:model-value="dirty = true" />

            <!-- 多选（distill.focus 这类） -->
            <UiField v-else-if="f.type === 'list' && f.choices" :label="f.label" :help="f.help">
              <div class="checks">
                <label v-for="c in f.choices" :key="c[0]" class="ck">
                  <input type="checkbox" :value="c[0]" v-model="form[f.path]"
                         @change="dirty = true">{{ c[1] }}
                </label>
              </div>
            </UiField>

            <!-- 列表（关键词这类） -->
            <UiField v-else-if="f.type === 'list'" :label="f.label" :help="f.help">
              <textarea rows="3" :value="(form[f.path] || []).join('\n')"
                        :placeholder="f.placeholder"
                        @input="form[f.path] = $event.target.value.split('\n').map(x => x.trim()).filter(Boolean); dirty = true"></textarea>
            </UiField>

            <!-- 下拉 -->
            <UiField v-else-if="f.choices" :label="f.label" :help="f.help">
              <UiSelect v-model="form[f.path]" :options="f.choices"
                        @update:model-value="dirty = true" />
            </UiField>

            <!-- 行式编辑器：提供商 / 团队成员 -->
            <UiField v-else-if="f.type === 'providerlist'" :label="f.label" :help="f.help">
              <UiListEditor v-model="form[f.path]" :columns="listColumns.provider"
                            :new-row="{ name: '', base_url: '', api_key: '' }"
                            add-label="添加提供商" empty-hint="还没有其他提供商；只用品 .env 里的主模型时不用配。"
                            @change="dirty = true" />
            </UiField>
            <UiField v-else-if="f.type === 'agentlist'" :label="f.label" :help="f.help">
              <UiListEditor v-model="form[f.path]" :columns="listColumns.agent"
                            :new-row="{ name: '', model: '', thinking: '', perspective: '' }"
                            add-label="添加成员" empty-hint="还没有团队成员。"
                            @change="dirty = true" />
            </UiField>

            <!-- 数字 -->
            <UiField v-else-if="f.type === 'int' || f.type === 'float'"
                     :label="f.label" :help="f.help" :unit="f.unit">
              <input type="number" v-model.number="form[f.path]"
                     :min="f.min" :max="f.max" :step="f.step || 1"
                     @input="dirty = true">
            </UiField>

            <!-- 文本 -->
            <UiField v-else :label="f.label" :help="f.help">
              <input type="text" v-model="form[f.path]" :placeholder="f.placeholder"
                     @input="dirty = true">
            </UiField>
          </template>
        </div>
      </template>
    </UiCard>

    <div v-if="tab !== 'prompts'" class="savebar">
      <span v-if="dirty" class="warn"><UiBadge tone="accent">有未保存的修改</UiBadge></span>
      <span v-else class="ok">已是最新</span>
      <UiBtn variant="primary" :loading="saving" :disabled="!dirty" @click="save">保存全部设置</UiBtn>
    </div>
  </div>
</template>

<style scoped>
.view{display:flex;flex-direction:column;gap:var(--sp-4)}
.presets{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:var(--sp-3)}
.preset{display:flex;flex-direction:column;gap:4px;text-align:left;
  padding:var(--sp-3) var(--sp-4);border:1px solid var(--line2);
  border-radius:var(--r-md);background:var(--surface);
  transition:border-color var(--dur-fast),background var(--dur-fast)}
.preset:hover{border-color:var(--accent);background:var(--hover)}
.preset.on{border-color:var(--accent);background:var(--accent-soft)}
.preset b{font-size:var(--fs-base)}
.preset span{font-size:var(--fs-xs);color:var(--ink3);line-height:1.6}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:var(--sp-4)}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.actions{display:flex;gap:var(--sp-2);margin-top:var(--sp-4)}
.testother{margin-top:var(--sp-4)}
.testrow{display:flex;gap:var(--sp-2)}
.testrow input{flex:1;min-width:0}
.fields{display:flex;flex-direction:column;gap:var(--sp-4);margin-top:var(--sp-4)}
.checks{display:flex;flex-wrap:wrap;gap:var(--sp-3)}
.ck{display:flex;align-items:center;gap:6px;font-size:var(--fs-sm);cursor:pointer}
.ck input{width:auto}
.nores{padding:var(--sp-6);text-align:center;color:var(--ink3)}
.savebar{position:sticky;bottom:56px;display:flex;align-items:center;
  justify-content:flex-end;gap:var(--sp-3);padding:var(--sp-3) var(--sp-4);
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r-lg);
  box-shadow:var(--shadow)}
.ok{font-size:var(--fs-sm);color:var(--ink3)}
</style>
