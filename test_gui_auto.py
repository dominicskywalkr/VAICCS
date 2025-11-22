from gui import App

app = App()

def schedule_actions():
    # start after 0.5s
    app.after(500, lambda: (print('AUTO: calling start_capture()'), app.start_capture()))
    # stop after 3.5s
    app.after(3500, lambda: (print('AUTO: calling stop_capture()'), app.stop_capture()))
    # destroy after 4s
    app.after(4000, lambda: (print('AUTO: destroying app'), app.destroy()))

app.after(0, schedule_actions)
print('AUTO: entering mainloop')
app.mainloop()
print('AUTO: mainloop exited')
