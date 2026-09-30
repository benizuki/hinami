<script setup lang="ts">
import { toRef } from 'vue'
import type { TenantRecord } from '../../../api/hinami'

const props = defineProps<{
  editingId: string
  activeTenantId: string
  form: TenantRecord
}>()

const open = defineModel<boolean>({ required: true })
const form = toRef(props, 'form')
const emit = defineEmits<{ save: [] }>()
</script>

<template>
  <v-dialog v-model="open" max-width="600">
    <v-card class="dialog-card">
      <v-card-title>{{ editingId ? 'テナントを編集' : 'テナントを追加' }}</v-card-title>
      <v-card-subtitle>このテナントの中で組織・利用者・日々の記録を管理します。</v-card-subtitle>
      <v-card-text>
        <div class="user-editor-grid">
          <label><span>テナントID（自動生成）</span><output class="department-id-display"><code>{{ form.id }}</code><v-icon size="16">mdi-lock-outline</v-icon></output><small>新規登録時に8文字のUIDを自動生成します。</small></label>
          <label><span>テナント名</span><input v-model="form.name" placeholder="例：東日本事業会社" /></label>
          <label class="user-editor-grid__wide"><span>説明</span><input v-model="form.description" placeholder="対象会社・拠点など" /></label>
          <label class="user-enabled-toggle"><input v-model="form.enabled" type="checkbox" :disabled="form.id === activeTenantId" /><span>有効にする</span></label>
        </div>
      </v-card-text>
      <v-card-actions><v-spacer></v-spacer><v-btn variant="text" @click="open = false">キャンセル</v-btn><v-btn color="primary" prepend-icon="mdi-content-save-outline" @click="emit('save')">保存</v-btn></v-card-actions>
    </v-card>
  </v-dialog>
</template>
