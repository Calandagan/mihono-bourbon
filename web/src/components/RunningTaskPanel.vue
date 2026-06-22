<template>
  <div>
    <div class="card">
      <div v-if="runningTask === undefined" class="card-body">
        <div class="d-flex align-items-center">
          <h5 class="mb-0">No running tasks</h5>
        </div>
      </div>
      <div v-if="runningTask !== undefined" class="card-body">
        <div class="d-flex align-items-center gap-12px">
          <h5 class="mb-0">Currently Running: {{runningTask['task_desc']}}</h5>
          <span class="ml-auto edit-task-btn" @click="onEditTask"><i class="fa fa-cog fa-lg"></i></span>
        </div>
        <div class="run-timer">
          <span class="timer-label">Elapsed</span>
          <span class="timer-value">{{ elapsedLabel || '00:00:00' }}</span>
        </div>
        <task-detail-info-handler :task="runningTask"></task-detail-info-handler>
      </div>
    </div>
  </div>
</template>

<script>
import TaskDetailInfoHandler from "./base/TaskDetailInfoHandler.vue";
export default {
  name: "RunningTaskPanel",
  props:["runningTask", "elapsedLabel"],
  data(){ return{} },
  components: { TaskDetailInfoHandler },
   methods: {
     onEditTask() {
       this.$emit('edit-task', this.runningTask);
     }
   }
 }
</script>
<style scoped>
.edit-task-btn {
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.edit-task-btn:hover {
  opacity: 1;
  transform: rotate(45deg);
}
.run-timer {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  margin-bottom: 6px;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.timer-label {
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}
.timer-value {
  color: #fff;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  font-size: 16px;
  font-weight: 800;
  letter-spacing: 0;
}
</style>
