<template>
  <div class="list-panel">
    <div class="mb-3">
      <auto-status-panel></auto-status-panel>
    </div>
    <div class="mb-3">
      <running-task-panel
        :running-task="runningTask"
        :elapsed-label="runningElapsedLabel"
        @edit-task="handleEditTask"
      ></running-task-panel>
    </div>
    <div class="mb-3">
      <waiting-task-list :waiting-task-list="waitingTaskList"></waiting-task-list>
    </div>
    <div class="mb-3">
      <history-task-list :history-task-list="historyTaskList"></history-task-list>
    </div>
    <div class="mb-3">
      <div class="card image-card">
        <div class="card-body">
          <div class="image-layer" :style="{ '--image-url': `url(${imageBg})` }"></div>
        </div>
      </div>
    </div>
    <div v-if="detectedSkills && detectedSkills.length > 0" class="mb-3">
      <detected-skills-panel :skills="detectedSkills"></detected-skills-panel>
    </div>
    <div v-if="detectedPortraits && detectedPortraits.length > 0" class="mb-3">
      <detected-portraits-panel :portraits="detectedPortraits"></detected-portraits-panel>
    </div>
    <div v-if="detectedShopItems && detectedShopItems.length > 0" class="mb-3">
      <detected-shop-panel :items="detectedShopItems"></detected-shop-panel>
    </div>
    <div v-if="detectedItems && detectedItems.length > 0" class="mb-3">
      <detected-items-panel :items="detectedItems"></detected-items-panel>
    </div>
    <div>
      <task-edit-modal ref="taskEditModal"></task-edit-modal>
    </div>
  </div>
</template>

<script>
import RunningTaskPanel from "@/components/RunningTaskPanel.vue";
import WaitingTaskList from "@/components/WaitingTaskList.vue";
import AutoStatusPanel from "@/components/AutoStatusPanel.vue";
import TaskEditModal from "@/components/TaskEditModal.vue";
import HistoryTaskList from "@/components/HistoryTaskList.vue";
import CronJobList from "@/components/CronJobList.vue";
import DetectedSkillsPanel from "@/components/DetectedSkillsPanel.vue";
import DetectedPortraitsPanel from "@/components/DetectedPortraitsPanel.vue";
import DetectedItemsPanel from "@/components/DetectedItemsPanel.vue";
import DetectedShopPanel from "@/components/DetectedShopPanel.vue";

import imageBgUrl1 from "../../assets/cunny.png";
export default {
  name: "SchedulerPanel",
  components: { CronJobList, HistoryTaskList, TaskEditModal, WaitingTaskList, AutoStatusPanel, RunningTaskPanel, DetectedSkillsPanel, DetectedPortraitsPanel, DetectedItemsPanel, DetectedShopPanel },
  props: ["runningTask", "waitingTaskList", "historyTaskList", "cronJobList", "detectedSkills", "detectedPortraits", "detectedItems", "detectedShopItems", "runningElapsedLabel"],
  data(){
    return {
      imageBg: imageBgUrl1
    }
  },
  mounted() {
    this.applyTheme();
  },
  methods: {
    handleEditTask(task) {
      const taskId = task.task_id;
      this.axios.delete("/task", { task_id: taskId }).then(() => {
        this.$refs.taskEditModal.loadFromTask(task);
        this.$refs.taskEditModal.showModal();
      }).catch(e => {
        ;
      });
    },
    applyTheme() {
      document.documentElement.classList.remove('theme-blue');
      document.documentElement.classList.add('theme-pink');
    }
  }
}
</script>

<style scoped>
.list-panel{display:flex;flex-direction:column;height:100%}
.list-panel .card{margin-bottom:0}
.image-card{flex:1 1 auto;display:flex}
.image-card .card-body{height:392px;min-height:392px;flex:0 0 auto;border-radius:12px;overflow:hidden}
.image-card .image-layer{width:100%;height:100%;min-height:100%;background:transparent var(--image-url) center/contain no-repeat !important}
.list-panel> .mb-3:last-child{margin-bottom:0}
.list-title{font-weight:700}
.list-empty{color:var(--muted)}
</style>
