<template>
  <div class="card">
    <div class="card-body">
      <div class="shop-header" @click="expanded = !expanded">
        <h5 class="mb-0">Shop Items <span class="item-count-badge" v-if="items.length">{{ items.length }}</span></h5>
        <span class="toggle-text">{{ expanded ? '▲' : '▼' }}</span>
      </div>
      <div v-if="expanded" class="shop-body">
        <div v-if="items.length === 0" class="empty-state">No shop items detected yet</div>
        <div v-else class="shop-list">
          <div
            v-for="item in sortedItems"
            :key="item.name"
            class="shop-item-row"
            :class="{ purchased: item.purchased }"
          >
            <div class="item-info">
              <img v-if="getItemIcon(item.name)" :src="getItemIcon(item.name)" :alt="item.name" class="item-icon" />
              <span class="item-name">{{ item.name }}</span>
            </div>
            <div class="item-meta">
              <span v-if="item.turns < 99" class="turns-badge">{{ item.turns }}T</span>
              <span v-if="item.purchased" class="purchased-badge">Bought</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
const iconModules = import.meta.glob('../assets/img/mant_items/*.png', { eager: true })

const iconMap = {}
for (const path in iconModules) {
  const filename = path.split('/').pop().replace('.png', '')
  iconMap[filename] = iconModules[path].default
}

function nameToSlug(name) {
  return name.toLowerCase().replace(/'/g, '').replace(/ /g, '_')
}

export default {
  name: "DetectedShopPanel",
  props: {
    items: { type: Array, default: () => [] }
  },
  data() {
    return { expanded: true }
  },
  computed: {
    sortedItems() {
      return [...this.items].sort((a, b) => {
        const ta = a.turns < 99 ? a.turns : 999
        const tb = b.turns < 99 ? b.turns : 999
        if (ta !== tb) return ta - tb
        return a.name.localeCompare(b.name)
      })
    }
  },
  methods: {
    getItemIcon(name) {
      return iconMap[nameToSlug(name)] || null
    }
  }
}
</script>

<style scoped>
.shop-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  padding: 2px 0;
}
.shop-header:hover { opacity: .85 }
.toggle-text { color: var(--muted); font-size: 12px }
.item-count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 6px;
  border-radius: 9999px;
  background: linear-gradient(135deg, var(--accent), var(--accent-2));
  color: #fff;
  font-size: 11px;
  font-weight: 800;
  margin-left: 8px;
  vertical-align: middle;
}
.shop-body { margin-top: 12px }
.shop-list { display: flex; flex-direction: column; gap: 6px; max-height: 320px; overflow-y: auto }
.shop-item-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 8px;
  background: rgba(255,255,255,.02);
  transition: all .2s;
}
.shop-item-row:hover {
  border-color: var(--accent);
  background: rgba(255,255,255,.04);
}
.shop-item-row.purchased { opacity: 0.45 }
.item-info { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1 }
.item-icon { width: 28px; height: 28px; border-radius: 4px; object-fit: contain; flex-shrink: 0 }
.item-name { font-weight: 600; font-size: 13px; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.item-meta { display: flex; align-items: center; gap: 6px; flex-shrink: 0; margin-left: 8px }
.turns-badge {
  font-size: 11px;
  font-weight: 700;
  color: var(--accent);
  background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 4px;
  padding: 1px 5px;
}
.purchased-badge {
  font-size: 10px;
  font-weight: 700;
  color: var(--muted);
  background: rgba(255,255,255,.04);
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 4px;
  padding: 1px 5px;
}
.empty-state { color: var(--muted); font-size: 13px; padding: 8px 0 }
</style>
